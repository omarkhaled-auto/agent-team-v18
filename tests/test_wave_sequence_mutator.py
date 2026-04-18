"""Phase G Slice 3 — wave-sequence mutator strips flag-gated slots.

``wave_executor.WAVE_SEQUENCES`` carries the Phase-G target sequence per
template:

    full_stack  -> [A, A5, Scaffold, B, C, D, T, T5, E]
    backend_only -> [A, A5, Scaffold, B, C, T, T5, E]
    frontend_only -> [A, Scaffold, D, T, T5, E]

``wave_executor._wave_sequence(template, config)`` mutates these lists
at call time:

- ``A5`` is stripped when ``v18.wave_a5_enabled`` is False.
- ``T5`` is stripped when ``v18.wave_t5_enabled`` is False.
- ``Scaffold`` is stripped when ``v18.scaffold_verifier_enabled`` is False.
- ``T`` is stripped when ``v18.wave_t_enabled`` is False.
- ``D5`` is RE-inserted after ``D`` when ``v18.wave_d_merged_enabled`` is
  False AND legacy Wave D.5 is enabled (preserving pre-Phase-G ordering).
"""

from __future__ import annotations

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import WAVE_SEQUENCES, _wave_sequence


def _config_all_on() -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a5_enabled = True
    cfg.v18.wave_t5_enabled = True
    cfg.v18.wave_t_enabled = True
    cfg.v18.scaffold_verifier_enabled = True
    cfg.v18.wave_d_merged_enabled = True
    return cfg


def _config_all_off() -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a5_enabled = False
    cfg.v18.wave_t5_enabled = False
    cfg.v18.wave_t_enabled = False
    cfg.v18.scaffold_verifier_enabled = False
    cfg.v18.wave_d_merged_enabled = False
    return cfg


def test_sequences_declared_for_three_templates() -> None:
    for template in ("full_stack", "backend_only", "frontend_only"):
        assert template in WAVE_SEQUENCES
        assert "A" in WAVE_SEQUENCES[template]


def test_full_stack_with_all_flags_on_has_all_phase_g_slots() -> None:
    waves = _wave_sequence("full_stack", _config_all_on())
    assert "A5" in waves
    assert "T5" in waves
    assert "T" in waves
    assert "Scaffold" in waves
    # Merged-D → no D5 re-insertion.
    assert "D5" not in waves


def test_full_stack_with_a5_off_strips_a5() -> None:
    cfg = _config_all_on()
    cfg.v18.wave_a5_enabled = False
    waves = _wave_sequence("full_stack", cfg)
    assert "A5" not in waves
    # Other slots remain.
    assert "T5" in waves


def test_full_stack_with_t5_off_strips_t5() -> None:
    cfg = _config_all_on()
    cfg.v18.wave_t5_enabled = False
    waves = _wave_sequence("full_stack", cfg)
    assert "T5" not in waves
    assert "A5" in waves


def test_full_stack_with_wave_d_merged_off_reinserts_d5() -> None:
    cfg = _config_all_on()
    cfg.v18.wave_d_merged_enabled = False
    # wave_d5 enabled by default — the re-insertion condition should fire.
    waves = _wave_sequence("full_stack", cfg)
    assert "D" in waves
    assert "D5" in waves
    # D5 sits immediately after D (preserves pre-Phase-G ordering).
    assert waves.index("D5") == waves.index("D") + 1


def test_backend_only_has_no_d_slot_in_any_config() -> None:
    """Backend-only template has no frontend wave — no D slot to mutate."""
    cfg_on = _config_all_on()
    cfg_off = _config_all_off()
    assert "D" not in WAVE_SEQUENCES["backend_only"]
    assert "D" not in _wave_sequence("backend_only", cfg_on)
    assert "D" not in _wave_sequence("backend_only", cfg_off)


def test_frontend_only_never_carries_a5() -> None:
    """Frontend-only template has no Wave A plan review to re-audit."""
    cfg = _config_all_on()
    assert "A5" not in WAVE_SEQUENCES["frontend_only"]
    assert "A5" not in _wave_sequence("frontend_only", cfg)


def test_all_off_preserves_pre_phase_g_byte_layout_full_stack() -> None:
    """With every Phase G flag OFF, full_stack collapses to the legacy
    ``[A, B, C, D, D5, E]`` plus whatever else the legacy defaults carry.
    The important property: no NEW Phase-G slots leak in flag-off mode."""
    cfg = _config_all_off()
    waves = _wave_sequence("full_stack", cfg)
    assert "A5" not in waves
    assert "T5" not in waves
    assert "Scaffold" not in waves
    assert "T" not in waves

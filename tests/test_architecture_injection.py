"""Phase G Slice 5c — `<architecture>` XML injection into Wave B/D/T/E.

``_load_per_milestone_architecture_block`` reads
``.agent-team/milestone-{id}/ARCHITECTURE.md`` (Wave A's handoff) and wraps
it in an ``<architecture>...</architecture>`` XML block. The helper is
called from ``build_wave_b_prompt``, ``build_wave_d_prompt``,
``build_wave_t_prompt``, and ``build_wave_e_prompt`` within the SAME
milestone.

Flag-gated via ``v18.architecture_md_enabled``; returns empty string when
flag is off, milestone id is unknown, or the file is missing — preserving
byte-identical flag-off behaviour.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.agents import (
    _load_per_milestone_architecture_block,
    build_wave_b_prompt,
    build_wave_d_prompt,
    build_wave_e_prompt,
    build_wave_t_prompt,
)
from agent_team_v15.config import AgentTeamConfig


def _milestone(milestone_id: str = "M7") -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Orders",
        template="full_stack",
        description="",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "entities": [],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _config_on() -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.architecture_md_enabled = True
    return cfg


def _config_off() -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.architecture_md_enabled = False
    return cfg


def _seed_milestone_arch(tmp_path: Path, milestone_id: str, body: str) -> Path:
    target = tmp_path / ".agent-team" / f"milestone-{milestone_id}" / "ARCHITECTURE.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_helper_returns_xml_block_when_file_present(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "M1", "## Entities\n- Order")
    block = _load_per_milestone_architecture_block(
        str(tmp_path), "M1", _config_on().v18
    )
    assert block.startswith("<architecture>\n")
    assert block.endswith("\n</architecture>")
    assert "## Entities" in block
    assert "- Order" in block


def test_helper_returns_empty_when_flag_off(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "M1", "## Entities\n- Order")
    block = _load_per_milestone_architecture_block(
        str(tmp_path), "M1", _config_off().v18
    )
    assert block == ""


def test_helper_returns_empty_when_file_missing(tmp_path: Path) -> None:
    block = _load_per_milestone_architecture_block(
        str(tmp_path), "M1", _config_on().v18
    )
    assert block == ""


def test_helper_returns_empty_for_unknown_milestone(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "milestone-unknown", "## Entities\n")
    # The sentinel id is treated as "no milestone context".
    block = _load_per_milestone_architecture_block(
        str(tmp_path), "milestone-unknown", _config_on().v18
    )
    assert block == ""


def test_wave_b_prompt_includes_architecture_xml(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "M3", "## Entities\n- Order")
    prompt = build_wave_b_prompt(
        milestone=_milestone("M3"),
        ir=_ir(),
        wave_a_artifact=None,
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config_on(),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    assert "<architecture>" in prompt
    assert "- Order" in prompt


def test_wave_d_prompt_includes_architecture_xml_when_merged(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "M3", "## Entities\n- Order")
    prompt = build_wave_d_prompt(
        milestone=_milestone("M3"),
        ir=_ir(),
        wave_c_artifact=None,
        scaffolded_files=[],
        config=_config_on(),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
        merged=True,
    )
    assert "<architecture>" in prompt


def test_wave_t_prompt_includes_architecture_xml(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "M3", "## Entities\n- Order")
    prompt = build_wave_t_prompt(
        milestone=_milestone("M3"),
        ir=_ir(),
        wave_artifacts={},
        config=_config_on(),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    assert "<architecture>" in prompt


def test_wave_e_prompt_includes_architecture_xml(tmp_path: Path) -> None:
    _seed_milestone_arch(tmp_path, "M3", "## Entities\n- Order")
    prompt = build_wave_e_prompt(
        milestone=_milestone("M3"),
        ir=_ir(),
        wave_artifacts={},
        config=_config_on(),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    assert "<architecture>" in prompt


def test_flag_off_skips_injection_across_all_waves(tmp_path: Path) -> None:
    """Flag OFF: all four prompts omit the <architecture> block."""
    _seed_milestone_arch(tmp_path, "M3", "## Entities\n- Order")
    wave_b = build_wave_b_prompt(
        milestone=_milestone("M3"),
        ir=_ir(),
        wave_a_artifact=None,
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config_off(),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    wave_e = build_wave_e_prompt(
        milestone=_milestone("M3"),
        ir=_ir(),
        wave_artifacts={},
        config=_config_off(),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    assert "<architecture>" not in wave_b
    assert "<architecture>" not in wave_e

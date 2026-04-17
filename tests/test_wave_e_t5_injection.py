"""Phase G Slice 5d — Wave T.5 gap list injection into Wave E prompt.

``_load_wave_t5_gap_block`` reads
``.agent-team/milestones/{id}/WAVE_T5_GAPS.json`` and renders a
``<wave_t5_gaps>...</wave_t5_gaps>`` block. ``build_wave_e_prompt``
includes it when ``v18.wave_t5_gap_list_inject_wave_e=True`` AND the gap
artifact exists and contains non-empty ``gaps``. Flag OFF or empty/missing
gaps → block is omitted (byte-identical pre-Phase-G).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.agents import build_wave_e_prompt, _load_wave_t5_gap_block
from agent_team_v15.config import AgentTeamConfig


def _seed_gaps(tmp_path: Path, milestone_id: str, gaps: list[dict]) -> Path:
    target = (
        tmp_path / ".agent-team" / "milestones" / milestone_id / "WAVE_T5_GAPS.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"gaps": gaps, "files_read": []}), encoding="utf-8"
    )
    return target


def _config(*, flag: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_t5_gap_list_inject_wave_e = flag
    return cfg


def _milestone(milestone_id: str = "M1") -> SimpleNamespace:
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


def test_gap_block_renders_xml_with_serialized_list(tmp_path: Path) -> None:
    _seed_gaps(
        tmp_path,
        "M1",
        [
            {
                "test_file": "apps/api/users.service.spec.ts",
                "source_symbol": "UsersService.create",
                "ac_id": "AC-1",
                "category": "missing_edge_case",
                "severity": "HIGH",
                "missing_case": "empty email",
                "suggested_assertion": "expect(...).toThrow()",
            }
        ],
    )
    block = _load_wave_t5_gap_block(str(tmp_path), "M1", _config(flag=True).v18)
    assert "<wave_t5_gaps>" in block
    assert "</wave_t5_gaps>" in block
    assert "UsersService.create" in block
    assert "Playwright" in block


def test_gap_block_flag_off_returns_empty(tmp_path: Path) -> None:
    _seed_gaps(tmp_path, "M1", [{"severity": "HIGH", "missing_case": "x"}])
    block = _load_wave_t5_gap_block(str(tmp_path), "M1", _config(flag=False).v18)
    assert block == ""


def test_gap_block_returns_empty_when_gaps_missing(tmp_path: Path) -> None:
    _seed_gaps(tmp_path, "M1", [])  # empty list
    block = _load_wave_t5_gap_block(str(tmp_path), "M1", _config(flag=True).v18)
    assert block == ""


def test_wave_e_prompt_includes_gap_block_when_flag_on(tmp_path: Path) -> None:
    _seed_gaps(
        tmp_path,
        "M1",
        [
            {
                "test_file": "x.spec.ts",
                "source_symbol": "doThing",
                "ac_id": None,
                "category": "weak_assertion",
                "severity": "HIGH",
                "missing_case": "weak assertion",
                "suggested_assertion": "assert strict shape",
            }
        ],
    )
    prompt = build_wave_e_prompt(
        milestone=_milestone("M1"),
        ir=_ir(),
        wave_artifacts={},
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    assert "<wave_t5_gaps>" in prompt
    assert "doThing" in prompt


def test_wave_e_prompt_omits_gap_block_when_flag_off(tmp_path: Path) -> None:
    _seed_gaps(
        tmp_path,
        "M1",
        [{"severity": "CRITICAL", "missing_case": "x"}],
    )
    prompt = build_wave_e_prompt(
        milestone=_milestone("M1"),
        ir=_ir(),
        wave_artifacts={},
        config=_config(flag=False),
        existing_prompt_framework="FRAMEWORK",
        cwd=str(tmp_path),
    )
    assert "<wave_t5_gaps>" not in prompt

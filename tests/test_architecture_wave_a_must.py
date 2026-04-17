"""Phase G Slice 1c/5a — R3 per-milestone ARCHITECTURE.md MUST rule.

Wave A's prompt carries a `[PER-MILESTONE ARCHITECTURE HANDOFF — MUST]`
section instructing Claude to write
``.agent-team/milestone-{milestone_id}/ARCHITECTURE.md`` alongside its
backend scaffolding output. The file is then consumed by Wave B/D/T/E of
the SAME milestone via ``<architecture>`` XML injection (Slice 5c).

These tests assert:
1. The MUST section appears only when ``v18.architecture_md_enabled=True``.
2. The referenced output path interpolates the milestone id.
3. The MUST section is silent when the flag is OFF (byte-identical pre-G).
4. The prompt distinguishes this file from the repo-root cumulative doc.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.agents import build_wave_a_prompt
from agent_team_v15.config import AgentTeamConfig


def _milestone(milestone_id: str = "M3") -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Orders",
        template="full_stack",
        description="orders milestone",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _config(*, flag: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.architecture_md_enabled = flag
    return cfg


def test_wave_a_prompt_contains_must_when_flag_on() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
    )
    assert "[PER-MILESTONE ARCHITECTURE HANDOFF — MUST]" in prompt
    # Output path interpolates the milestone id.
    assert ".agent-team/milestone-M3/ARCHITECTURE.md" in prompt
    # Distinguishes the per-milestone file from the cumulative repo-root doc.
    assert "DIFFERENT from the repo-root" in prompt


def test_wave_a_prompt_omits_must_when_flag_off() -> None:
    """Default (flag OFF) keeps prompt byte-identical to pre-Phase-G shape."""
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=False),
        existing_prompt_framework="FRAMEWORK",
    )
    assert "[PER-MILESTONE ARCHITECTURE HANDOFF — MUST]" not in prompt
    assert ".agent-team/milestone-M3/ARCHITECTURE.md" not in prompt


def test_must_interpolates_different_milestone_ids() -> None:
    """Each milestone's prompt names its OWN output path (no cross-talk)."""
    for mid in ("M1", "M2", "milestone-orders", "m-42"):
        prompt = build_wave_a_prompt(
            milestone=_milestone(milestone_id=mid),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=[],
            config=_config(flag=True),
            existing_prompt_framework="FRAMEWORK",
        )
        assert f".agent-team/milestone-{mid}/ARCHITECTURE.md" in prompt


def test_must_describes_content_scope() -> None:
    """The MUST spec should list the expected content — not code, just seams."""
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
    )
    # Content scope: entities/relations/indexes/migration filenames/service seams.
    assert "entities" in prompt
    assert "relations" in prompt
    # No code guidance.
    assert "no code" in prompt or "<=200 lines" in prompt

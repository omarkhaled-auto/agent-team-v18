"""Wave B/D core prompts must be provider-neutral so claude fallback inherits scope.

Bug: build-d-rerun-20260414's Wave D codex 429'd ("at capacity"); the claude
fallback wrote 1 file (apps/web/tsconfig.tsbuildinfo as a TS cache artifact)
vs codex's typical ~43 files. Root cause: build_wave_d_prompt() emits the
literal `"You are Codex operating in full-autonomous frontend implementation
mode for Wave D."` and passes that brief verbatim to claude, which (a)
identifies as the wrong agent and (b) lacks codex-specific persistence
directives that the codex wrap (CODEX_WAVE_D_PREAMBLE) added separately.

Fix: neutralize the role line in the core wave prompts so the brief is truly
provider-agnostic. Codex retains its preamble/suffix wrap; claude receives the
same neutralized brief without any "You are Codex" identification.
"""
from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.agents import build_wave_b_prompt, build_wave_d_prompt
from agent_team_v15.config import AgentTeamConfig


FRAMEWORK_MARKER = "FRAMEWORK_MARKER\nUse @ApiProperty() on DTO fields.\n"


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-orders",
        title="Orders",
        template="full_stack",
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "project_name": "Demo",
        "entities": [{"name": "Order", "owner_feature": "F-ORDERS",
                       "fields": [{"name": "id", "type": "string"}]}],
        "endpoints": [{"method": "GET", "path": "/orders",
                        "owner_feature": "F-ORDERS", "description": "List"}],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [{"id": "AC-1", "feature": "F-ORDERS", "text": "List"}],
    }


class TestWaveDPromptIsProviderNeutral:
    def test_wave_d_prompt_does_not_say_you_are_codex(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"],
                              "endpoints": [{"method": "GET", "path": "/orders"}]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "You are Codex" not in prompt, (
            "Wave D core prompt must be provider-neutral so claude fallback "
            "inherits the same brief — see build-d-rerun-20260414 fallback evidence."
        )

    def test_wave_d_prompt_still_identifies_role(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_c_artifact={"client_exports": [],
                              "endpoints": []},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "Wave D" in prompt
        assert "frontend" in prompt.lower()


class TestWaveBPromptIsProviderNeutral:
    def test_wave_b_prompt_does_not_say_you_are_codex(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "You are Codex" not in prompt

    def test_wave_b_prompt_still_identifies_role(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "Wave B" in prompt
        assert "backend" in prompt.lower()

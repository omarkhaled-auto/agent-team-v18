from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.agents import (
    build_wave_a_prompt,
    build_wave_b_prompt,
    build_wave_d_prompt,
    build_wave_d5_prompt,
    build_wave_e_prompt,
)
from agent_team_v15.config import AgentTeamConfig

FRAMEWORK_MARKER = "FRAMEWORK_MARKER\nUse @ApiProperty() on DTO fields.\n"


def _milestone(
    milestone_id: str = "milestone-orders",
    *,
    title: str = "Orders",
    template: str = "full_stack",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title=title,
        template=template,
        description=f"{title} milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "project_name": "Demo",
        "entities": [
            {
                "name": "Order",
                "owner_feature": "F-ORDERS",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "total", "type": "number"},
                ],
            }
        ],
        "endpoints": [
            {
                "method": "GET",
                "path": "/orders",
                "owner_feature": "F-ORDERS",
                "description": "List orders",
            }
        ],
        "business_rules": [
            {
                "id": "BR-1",
                "service": "orders",
                "entity": "Order",
                "description": "Total must stay positive",
            }
        ],
        "integrations": [
            {
                "vendor": "Stripe",
                "port_name": "PaymentsPort",
                "type": "payment",
                "methods_used": ["chargeOrder"],
            }
        ],
        "acceptance_criteria": [
            {"id": "AC-1", "feature": "F-ORDERS", "text": "Show the orders list"}
        ],
        "i18n": {"locales": ["en", "ar"], "rtl_locales": ["ar"]},
    }


class TestWaveAPrompt:
    def test_includes_existing_framework(self) -> None:
        prompt = build_wave_a_prompt(
            milestone=_milestone(),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=["apps/api/src/orders/order.entity.ts"],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert prompt.startswith("FRAMEWORK_MARKER")

    def test_contains_entity_definitions(self) -> None:
        prompt = build_wave_a_prompt(
            milestone=_milestone(),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "Order" in prompt
        assert "id: string" in prompt
        assert "total: number" in prompt

    def test_does_not_contain_frontend_specs(self) -> None:
        prompt = build_wave_a_prompt(
            milestone=_milestone(),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "THE ONLY ALLOWED BACKEND ACCESS PATH" not in prompt
        assert "translation-key" not in prompt
        assert "manual fetch" not in prompt.lower()

    def test_instructs_tasks_md_update(self) -> None:
        prompt = build_wave_a_prompt(
            milestone=_milestone(),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "TASKS.md" in prompt

    def test_injects_stack_contract_block_twice(self) -> None:
        prompt = build_wave_a_prompt(
            milestone=_milestone(),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
            stack_contract={
                "backend_framework": "nestjs",
                "frontend_framework": "nextjs",
                "orm": "prisma",
                "database": "postgresql",
                "monorepo_layout": "apps",
                "backend_path_prefix": "apps/api/",
                "frontend_path_prefix": "apps/web/",
                "forbidden_file_patterns": [r".*\.entity\.ts$"],
                "forbidden_imports": ["@nestjs/typeorm"],
                "forbidden_decorators": ["@Entity"],
                "required_file_patterns": [r"prisma/schema\.prisma$"],
                "required_imports": ["@prisma/client"],
                "derived_from": ["prd_text"],
                "confidence": "explicit",
            },
        )

        assert prompt.count("=== STACK CONTRACT (NON-NEGOTIABLE) ===") == 2
        assert "WAVE_A_CONTRACT_CONFLICT.md" in prompt

    def test_includes_rejection_context_when_present(self) -> None:
        prompt = build_wave_a_prompt(
            milestone=_milestone(),
            ir=_ir(),
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
            stack_contract={
                "backend_framework": "nestjs",
                "frontend_framework": "nextjs",
                "orm": "prisma",
                "database": "postgresql",
                "monorepo_layout": "apps",
                "backend_path_prefix": "apps/api/",
                "frontend_path_prefix": "apps/web/",
                "forbidden_file_patterns": [r".*\.entity\.ts$"],
                "forbidden_imports": ["@nestjs/typeorm"],
                "forbidden_decorators": ["@Entity"],
                "required_file_patterns": [r"prisma/schema\.prisma$"],
                "required_imports": ["@prisma/client"],
                "derived_from": ["prd_text"],
                "confidence": "explicit",
            },
            stack_contract_rejection_context="- [STACK-FILE-001] apps/api/src/users/user.entity.ts:1 forbidden file",
        )

        assert "[PRIOR ATTEMPT REJECTED]" in prompt
        assert "STACK-FILE-001" in prompt


class TestWaveBPrompt:
    def test_includes_existing_framework(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={"entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}]},
            dependency_artifacts={},
            scaffolded_files=["apps/api/src/orders/orders.service.ts"],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert prompt.startswith("FRAMEWORK_MARKER")

    def test_contains_wave_a_entities(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={"entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}]},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "ENTITIES AVAILABLE FROM WAVE A" in prompt
        assert "Order" in prompt

    def test_contains_endpoint_specs(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "GET /orders" in prompt
        assert "List orders" in prompt

    def test_contains_adapter_ports(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "PaymentsPort" in prompt
        assert "chargeOrder" in prompt

    def test_does_not_contain_frontend_specs(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "THE ONLY ALLOWED BACKEND ACCESS PATH" not in prompt
        assert "translation-key" not in prompt
        assert "manual fetch" not in prompt.lower()

    def test_requires_api_property_decorators(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_a_artifact={},
            dependency_artifacts={},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "@ApiProperty" in prompt
        assert "@ApiPropertyOptional" in prompt
        assert "Wave C generates the typed client from DTO Swagger metadata." in prompt


class TestWaveDPrompt:
    def test_includes_existing_framework(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"], "endpoints": [{"method": "GET", "path": "/orders"}]},
            scaffolded_files=["apps/web/src/app/orders/page.tsx"],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert prompt.startswith("FRAMEWORK_MARKER")

    def test_contains_generated_client_exports(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"], "endpoints": [{"method": "GET", "path": "/orders"}]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "listOrders" in prompt

    def test_prefers_structured_client_manifest_when_present(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={
                "client_manifest": [
                    {
                        "symbol": "listOrders",
                        "method": "GET",
                        "path": "/orders",
                        "request_type": "{ query?: { page?: number } }",
                        "response_type": "Order[]",
                    }
                ]
            },
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "client call: listOrders" in prompt
        assert "request: { query?: { page?: number } }" in prompt
        assert "response: Order[]" in prompt

    def test_prohibits_manual_fetch(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "Do NOT re-implement HTTP calls with `fetch`/`axios`." in prompt

    def test_does_not_contain_backend_internals(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"], "endpoints": [{"method": "GET", "path": "/orders"}]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "OrdersService" not in prompt
        assert "OrderRepository" not in prompt

    def test_requires_translation_keys(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "translation-key" in prompt

    def test_includes_final_immutable_rule_wording(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_c_artifact={"client_exports": ["listOrders"]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert (
            "For every backend interaction in this wave, you MUST import from "
            "`packages/api-client/` and call the generated functions. Do NOT "
            "re-implement HTTP calls with `fetch`/`axios`. Do NOT edit, refactor, "
            "or add files under `packages/api-client/*`"
        ) in prompt


class TestWaveD5Prompt:
    def test_ui_polish_constraints_are_present(self) -> None:
        prompt = build_wave_d5_prompt(
            milestone=_milestone(title="Orders UI"),
            ir=_ir(),
            wave_d_artifact={
                "files_created": ["apps/web/src/app/orders/page.tsx"],
                "files_modified": ["apps/web/src/components/orders-table.tsx"],
            },
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "[WAVE D.5 - UI POLISH SPECIALIST]" in prompt
        assert (
            "Do NOT modify data fetching, API calls, state management, form handlers, "
            "routing, or TypeScript interfaces. Only enhance visual presentation."
        ) in prompt
        assert "apps/web/src/app/orders/page.tsx" in prompt
        assert "apps/web/src/components/orders-table.tsx" in prompt


class TestWaveEPrompt:
    def test_includes_existing_framework(self) -> None:
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={"A": {"files_created": ["apps/api/src/orders/order.entity.ts"]}},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert prompt.startswith("FRAMEWORK_MARKER")

    def test_requires_requirements_md_sync(self) -> None:
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "REQUIREMENTS.md" in prompt
        assert "- [x]" in prompt

    def test_requires_tasks_md_sync(self) -> None:
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "TASKS.md" in prompt
        assert "Status: COMPLETE" in prompt

    def test_requires_review_cycles_increment(self) -> None:
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "review_cycles" in prompt

    def test_playwright_instructions_always_emitted_v182(self) -> None:
        # V18.2 decoupling: Playwright instructions are emitted regardless of
        # evidence_mode (they were previously gated on soft_gate/hard_gate).
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "Write 2-3 focused Playwright" in prompt
        assert "npx playwright test" in prompt

    def test_record_only_includes_scanners_and_evidence(self) -> None:
        # V18.2: record_only now emits wiring/playwright/evidence sections
        # (evidence records still written — only "disabled" suppresses).
        config = AgentTeamConfig()
        config.v18.evidence_mode = "record_only"
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=config,
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "[WIRING SCANNER - REQUIRED]" in prompt
        assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt
        assert "[EVIDENCE COLLECTION - REQUIRED]" in prompt

    def test_soft_gate_full_stack_includes_scanners_and_playwright(self) -> None:
        config = AgentTeamConfig()
        config.v18.evidence_mode = "soft_gate"
        config.v18.live_endpoint_check = True
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=config,
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "[WIRING SCANNER - REQUIRED]" in prompt
        assert "[I18N SCANNER - REQUIRED]" in prompt
        assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt
        assert "npx playwright test" in prompt
        assert "[EVIDENCE COLLECTION - REQUIRED]" in prompt

    def test_soft_gate_backend_only_uses_api_verification(self) -> None:
        config = AgentTeamConfig()
        config.v18.evidence_mode = "soft_gate"
        milestone = _milestone(template="backend_only")
        prompt = build_wave_e_prompt(
            milestone=milestone,
            ir=_ir(),
            wave_artifacts={},
            config=config,
            existing_prompt_framework=FRAMEWORK_MARKER,
        )

        assert "[API VERIFICATION SCRIPTS - REQUIRED]" in prompt
        assert "[PLAYWRIGHT TESTS - REQUIRED]" not in prompt

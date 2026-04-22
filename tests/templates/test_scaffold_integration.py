"""Integration tests: template drop fires during scaffold (Issue #14)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import codex_prompts, constitution_templates
from agent_team_v15.scaffold_runner import _scaffold_infra_template
from agent_team_v15.stack_contract import StackContract, write_stack_contract


def _make_config(use_infra_template: bool) -> SimpleNamespace:
    return SimpleNamespace(v18=SimpleNamespace(use_infra_template=use_infra_template))


class TestInfraTemplateDrop:
    def test_drops_when_stack_matches(self, tmp_path: Path) -> None:
        sc = StackContract(backend_framework="nestjs", frontend_framework="nextjs")
        write_stack_contract(tmp_path, sc)
        written = _scaffold_infra_template(tmp_path, config=_make_config(True))
        posix = {p.replace("\\", "/") for p in written}
        assert "apps/api/Dockerfile" in posix
        assert ".dockerignore" in posix
        assert (tmp_path / "apps/api/Dockerfile").exists()
        assert (tmp_path / ".dockerignore").exists()

    def test_skips_when_flag_disabled(self, tmp_path: Path) -> None:
        sc = StackContract(backend_framework="nestjs", frontend_framework="nextjs")
        write_stack_contract(tmp_path, sc)
        written = _scaffold_infra_template(tmp_path, config=_make_config(False))
        assert written == []
        assert not (tmp_path / "apps/api/Dockerfile").exists()

    def test_skips_when_stack_unknown(self, tmp_path: Path) -> None:
        sc = StackContract(backend_framework="django", frontend_framework="")
        write_stack_contract(tmp_path, sc)
        written = _scaffold_infra_template(tmp_path, config=_make_config(True))
        assert written == []
        assert not (tmp_path / "apps/api/Dockerfile").exists()

    def test_skips_when_no_stack_contract(self, tmp_path: Path) -> None:
        # No stack_contract.json written
        written = _scaffold_infra_template(tmp_path, config=_make_config(True))
        assert written == []

    def test_default_config_enables(self, tmp_path: Path) -> None:
        """Config=None defaults to enabled (matches V18Config.use_infra_template=True)."""
        sc = StackContract(backend_framework="nestjs", frontend_framework="nextjs")
        write_stack_contract(tmp_path, sc)
        written = _scaffold_infra_template(tmp_path, config=None)
        assert any("apps/api/Dockerfile" in p.replace("\\", "/") for p in written)

    def test_preserves_preexisting_file(self, tmp_path: Path) -> None:
        sc = StackContract(backend_framework="nestjs", frontend_framework="nextjs")
        write_stack_contract(tmp_path, sc)
        preexist = tmp_path / "apps/api/Dockerfile"
        preexist.parent.mkdir(parents=True, exist_ok=True)
        preexist.write_text("# SCAFFOLD-OWNED\n", encoding="utf-8")
        written = _scaffold_infra_template(tmp_path, config=_make_config(True))
        # Existing file must NOT be clobbered
        assert preexist.read_text(encoding="utf-8") == "# SCAFFOLD-OWNED\n"
        # .dockerignore (new) should have been written
        assert (tmp_path / ".dockerignore").exists()
        posix = {p.replace("\\", "/") for p in written}
        assert "apps/api/Dockerfile" not in posix


class TestWaveBInfrastructureContractInjection:
    # Note: the literal token '<infrastructure_contract>' appears once in the
    # static AUD-INFRA preamble as a cross-reference. We detect injection by
    # looking for 'Template: ' (the rendered block's first data line) which is
    # unique to the runtime-injected block.
    def test_no_injection_when_stack_contract_absent(self) -> None:
        out = codex_prompts.wrap_prompt_for_codex("B", "BODY")
        assert "Template: pnpm_monorepo" not in out

    def test_no_injection_when_infra_missing(self) -> None:
        out = codex_prompts.wrap_prompt_for_codex(
            "B", "BODY", stack_contract={"backend_framework": "nestjs"}
        )
        assert "Template: pnpm_monorepo" not in out

    def test_injects_when_stack_carries_infra(self) -> None:
        stack = {
            "backend_framework": "nestjs",
            "infrastructure_template": {
                "name": "pnpm_monorepo",
                "version": "1.0.0",
                "slots": {
                    "api_service_name": "api",
                    "web_service_name": "web",
                    "api_port": 4000,
                    "web_port": 3000,
                    "postgres_port": 5432,
                    "postgres_version": "16-alpine",
                },
            },
        }
        out = codex_prompts.wrap_prompt_for_codex("B", "BODY", stack_contract=stack)
        assert "<infrastructure_contract>" in out
        assert "Template: pnpm_monorepo-1.0.0" in out
        assert "api (NestJS, port 4000, WORKDIR /app/apps/api)" in out
        assert "web (Next.js, port 3000, WORKDIR /app/apps/web)" in out
        assert "PostgreSQL 16-alpine" in out

    def test_injection_does_not_affect_non_b_waves(self) -> None:
        stack = {
            "infrastructure_template": {
                "name": "pnpm_monorepo",
                "version": "1.0.0",
                "slots": {},
            }
        }
        out = codex_prompts.wrap_prompt_for_codex("D", "BODY", stack_contract=stack)
        assert "<infrastructure_contract>" not in out

    def test_with_redis_appended(self) -> None:
        stack = {
            "infrastructure_template": {
                "name": "pnpm_monorepo",
                "version": "1.0.0",
                "slots": {"with_redis": True},
            }
        }
        out = codex_prompts.wrap_prompt_for_codex("B", "BODY", stack_contract=stack)
        assert "Cache: Redis 7-alpine" in out


class TestAudInfraPreambleBar:
    def test_preamble_contains_aud_infra(self) -> None:
        assert "AUD-INFRA" in codex_prompts.CODEX_WAVE_B_PREAMBLE
        assert "PRE-GENERATED curated infrastructure" in codex_prompts.CODEX_WAVE_B_PREAMBLE


class TestAgentsMdInfrastructurePolicy:
    def test_agents_md_contains_infrastructure_policy(self) -> None:
        body = constitution_templates.render_agents_md()
        assert "<infrastructure_policy>" in body
        assert "</infrastructure_policy>" in body
        assert "Container infrastructure" in body
        assert "BLOCKED:" in body

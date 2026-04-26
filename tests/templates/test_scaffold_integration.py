"""Integration tests: template drop fires during scaffold (Issue #14)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import codex_prompts, constitution_templates
from agent_team_v15.scaffold_runner import (
    ScaffoldConfig,
    _scaffold_infra_template,
    run_scaffolding,
)
from agent_team_v15.stack_contract import (
    StackContract,
    load_stack_contract,
    write_stack_contract,
)


def _make_config(use_infra_template: bool) -> SimpleNamespace:
    return SimpleNamespace(v18=SimpleNamespace(use_infra_template=use_infra_template))


class TestInfraTemplateDrop:
    def test_run_scaffolding_threads_contract_ports_everywhere(self, tmp_path: Path) -> None:
        ir_path = tmp_path / "product.ir.json"
        ir_path.write_text(
            json.dumps(
                {
                    "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
                    "entities": [],
                    "i18n": {"locales": []},
                }
            ),
            encoding="utf-8",
        )

        run_scaffolding(
            ir_path,
            tmp_path,
            "milestone-1",
            [],
            stack_target="NestJS Next.js pnpm",
            scaffold_cfg=ScaffoldConfig(port=3001, web_port=3002),
        )

        assert "PORT=3001" in (tmp_path / ".env.example").read_text(encoding="utf-8")
        assert "FRONTEND_ORIGIN=http://localhost:3002" in (
            tmp_path / ".env.example"
        ).read_text(encoding="utf-8")
        assert "NEXT_PUBLIC_API_URL=http://localhost:3001/api" in (
            tmp_path / ".env.example"
        ).read_text(encoding="utf-8")
        assert "PORT=3001" in (
            tmp_path / "apps" / "api" / ".env.example"
        ).read_text(encoding="utf-8")
        assert "http://localhost:3002" in (
            tmp_path / "apps" / "api" / "src" / "config" / "env.validation.ts"
        ).read_text(encoding="utf-8")
        assert "process.env.PORT ?? 3001" in (
            tmp_path / "apps" / "api" / "src" / "main.ts"
        ).read_text(encoding="utf-8")
        assert "NEXT_PUBLIC_API_URL=http://localhost:3001/api" in (
            tmp_path / "apps" / "web" / ".env.example"
        ).read_text(encoding="utf-8")

        compose = (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
        assert '"3001:3001"' in compose
        assert '"3002:3002"' in compose
        assert "http://localhost:3001/api/health" in compose

        api_dockerfile = (tmp_path / "apps" / "api" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        web_dockerfile = (tmp_path / "apps" / "web" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        assert "EXPOSE 3001" in api_dockerfile
        assert "EXPOSE 3002" in web_dockerfile
        assert 'CMD ["pnpm", "next", "start", "-p", "3002"]' in web_dockerfile

        package_json = json.loads(
            (tmp_path / "apps" / "web" / "package.json").read_text(encoding="utf-8")
        )
        assert package_json["scripts"]["dev"] == "next dev -p 3002"
        assert package_json["scripts"]["start"] == "next start -p 3002"

        contract = load_stack_contract(tmp_path)
        assert contract is not None
        assert contract.api_port == 3001
        assert contract.web_port == 3002
        assert contract.ports == [3001, 3002, 5432]
        assert contract.infrastructure_template["slots"]["api_port"] == 3001
        assert contract.infrastructure_template["slots"]["web_port"] == 3002

    def test_drops_when_stack_matches(self, tmp_path: Path) -> None:
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
        write_stack_contract(tmp_path, sc)
        written = _scaffold_infra_template(tmp_path, config=_make_config(True))
        posix = {p.replace("\\", "/") for p in written}
        assert "apps/api/Dockerfile" in posix
        assert ".dockerignore" in posix
        assert (tmp_path / "apps/api/Dockerfile").exists()
        assert (tmp_path / ".dockerignore").exists()

    def test_skips_when_flag_disabled(self, tmp_path: Path) -> None:
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
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

    def test_skips_when_package_manager_not_pnpm(self, tmp_path: Path) -> None:
        # Path A gate: nestjs+nextjs alone is NOT enough — package_manager must
        # also be "pnpm". An npm/yarn/unknown stack correctly skips the drop.
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="npm",
        )
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
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
        write_stack_contract(tmp_path, sc)
        written = _scaffold_infra_template(tmp_path, config=None)
        assert any("apps/api/Dockerfile" in p.replace("\\", "/") for p in written)

    def test_preserves_preexisting_file(self, tmp_path: Path) -> None:
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
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

    def test_persists_infrastructure_template_on_stack_contract(
        self, tmp_path: Path
    ) -> None:
        """Issue #14 plumbing: successful drop writes the template metadata
        back onto stack_contract.infrastructure_template so
        wrap_prompt_for_codex can read it at Wave B dispatch time."""
        from agent_team_v15.stack_contract import load_stack_contract

        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
        write_stack_contract(tmp_path, sc)
        _scaffold_infra_template(tmp_path, config=_make_config(True))

        reloaded = load_stack_contract(tmp_path)
        assert reloaded is not None
        infra = reloaded.infrastructure_template
        assert infra["name"] == "pnpm_monorepo"
        assert infra["version"] == "2.0.0"
        assert infra["slots"]["api_service_name"] == "api"
        assert infra["slots"]["api_port"] == 4000
        assert infra["slots"]["web_port"] == 3000

    def test_no_writeback_when_template_skipped(
        self, tmp_path: Path
    ) -> None:
        """When the template is skipped (non-matching stack), stack contract
        must NOT grow an infrastructure_template key."""
        from agent_team_v15.stack_contract import load_stack_contract

        sc = StackContract(backend_framework="django", frontend_framework="")
        write_stack_contract(tmp_path, sc)
        _scaffold_infra_template(tmp_path, config=_make_config(True))

        reloaded = load_stack_contract(tmp_path)
        assert reloaded is not None
        assert reloaded.infrastructure_template == {}


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


class TestRuntimeInjectionEndToEnd:
    """End-to-end: drive the runtime prompt-construction path the wave
    executor uses at dispatch time and assert the ``<infrastructure_contract>``
    block lands in the final wrapped prompt.

    This is the test team-lead called out as REQUIRED by directive #8.
    Exercises the full chain:
        scaffold writes STACK_CONTRACT.json with infrastructure_template
         → provider_router._wrap_codex_prompt_with_contract loads it (or
           receives it explicitly from wave_executor)
         → codex_prompts.wrap_prompt_for_codex injects the block
         → final prompt string contains the block with service/port/WORKDIR data.
    """

    def test_runtime_injection_when_contract_loaded_from_cwd(
        self, tmp_path: Path
    ) -> None:
        """Full cwd-load path: scaffold drop persists template metadata, then
        the provider_router helper reads cwd and produces an injected prompt.
        Mirrors what happens at Wave B dispatch when the contract was written
        by scaffold_runner earlier in the milestone."""
        from agent_team_v15.provider_router import _wrap_codex_prompt_with_contract

        # 1. Simulate scaffold: stack + infrastructure_template on disk.
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
        write_stack_contract(tmp_path, sc)
        _scaffold_infra_template(tmp_path, config=_make_config(True))

        # 2. Drive the runtime wrap path (no explicit stack_contract kwarg
        #    — helper must fall back to loading from cwd).
        wrapped = _wrap_codex_prompt_with_contract(
            "B", "WAVE_B_BODY", str(tmp_path)
        )

        # 3. Prove the <infrastructure_contract> block is present with real data.
        assert "<infrastructure_contract>" in wrapped
        assert "</infrastructure_contract>" in wrapped
        assert "Template: pnpm_monorepo-2.0.0" in wrapped
        assert "api (NestJS, port 4000, WORKDIR /app/apps/api)" in wrapped
        assert "web (Next.js, port 3000, WORKDIR /app/apps/web)" in wrapped
        # AUD-INFRA preamble is always present for Wave B; the block is
        # the dynamic addition that proves the plumbing fires.
        assert "AUD-INFRA" in wrapped
        # The original body is preserved inside the wrapper.
        assert "WAVE_B_BODY" in wrapped

    def test_runtime_injection_when_contract_passed_explicitly(
        self, tmp_path: Path
    ) -> None:
        """Explicit-pass path (preferred): wave_executor threads the loaded
        contract through as a kwarg so there's no double-read from disk."""
        from agent_team_v15.provider_router import _wrap_codex_prompt_with_contract

        contract = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
            infrastructure_template={
                "name": "pnpm_monorepo",
                "version": "2.0.0",
                "slots": {
                    "api_service_name": "svc-api",
                    "web_service_name": "svc-web",
                    "api_port": 4040,
                    "web_port": 3003,
                    "postgres_port": 5432,
                    "postgres_version": "16-alpine",
                },
            },
        )
        # NOTE: no STACK_CONTRACT.json on disk — helper must use the kwarg.
        wrapped = _wrap_codex_prompt_with_contract(
            "B", "BODY", str(tmp_path), stack_contract=contract
        )

        assert "<infrastructure_contract>" in wrapped
        assert "Template: pnpm_monorepo-2.0.0" in wrapped
        # Explicit slot values flow through.
        assert "svc-api (NestJS, port 4040, WORKDIR /app/apps/svc-api)" in wrapped
        assert "svc-web (Next.js, port 3003, WORKDIR /app/apps/svc-web)" in wrapped

    def test_runtime_no_injection_when_no_contract_anywhere(
        self, tmp_path: Path
    ) -> None:
        """Negative guard: no contract on disk, no kwarg passed → no
        <infrastructure_contract> block in the wrapped prompt. Pre-Issue-14
        behavior is preserved for non-pnpm stacks."""
        from agent_team_v15.provider_router import _wrap_codex_prompt_with_contract

        wrapped = _wrap_codex_prompt_with_contract("B", "BODY", str(tmp_path))

        assert "Template: pnpm_monorepo" not in wrapped
        # AUD-INFRA preamble bar is still there (it's static, wave-B-scoped).
        assert "AUD-INFRA" in wrapped
        # Original body still wrapped.
        assert "BODY" in wrapped

    def test_runtime_explicit_contract_beats_disk(
        self, tmp_path: Path
    ) -> None:
        """When both are present, the explicit kwarg wins over the on-disk
        contract. This is the wave_executor path: it loads resolved_stack_contract
        once at milestone start, and re-passes it to every wave — disk drift
        during a run must not alter the injected block."""
        from agent_team_v15.provider_router import _wrap_codex_prompt_with_contract

        # On disk: default slots (api_port=4000).
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
        )
        write_stack_contract(tmp_path, sc)
        _scaffold_infra_template(tmp_path, config=_make_config(True))

        # Explicit kwarg: overridden api_port=9999.
        override = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            package_manager="pnpm",
            infrastructure_template={
                "name": "pnpm_monorepo",
                "version": "2.0.0",
                "slots": {"api_service_name": "api", "api_port": 9999},
            },
        )
        wrapped = _wrap_codex_prompt_with_contract(
            "B", "BODY", str(tmp_path), stack_contract=override
        )

        # The kwarg's port (9999) wins; disk's (4000) is not consulted.
        assert "api (NestJS, port 9999" in wrapped
        assert "port 4000" not in wrapped


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

"""A-09: wave scope filter unit tests.

Covers:
- MilestoneScope construction from REQUIREMENTS.md + MASTER_PLAN.
- IR/spec filtering to the current milestone.
- Scope-preamble injection into wave prompts (B + D).
- Post-wave validator that catches out-of-scope files_created.
- Feature flag honours pre-fix behaviour when disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from agent_team_v15.agents import build_wave_d_prompt
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.milestone_scope import (
    MilestoneScope,
    apply_scope_to_prompt,
    build_scope_for_milestone,
    files_outside_scope,
    parse_files_to_create,
)
from agent_team_v15.scope_filter import FilteredIR, filter_ir_to_scope
from agent_team_v15.wave_executor import (
    WaveResult,
    _apply_post_wave_scope_validation,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal synthetic master_plan + REQUIREMENTS.md for M1 and M3.
# ---------------------------------------------------------------------------

M1_REQUIREMENTS_MD = """# Milestone 1: Platform Foundation

## Overview
- ID: milestone-1
- Template: full_stack
- AC-Refs: (none — infrastructure milestone)

## Description
Scaffold the NestJS + Next.js monorepo.

## Notes
- No feature business logic in this milestone
- JWT module is wired but has no strategies — strategies are added in M2
- next-intl locale files start empty — keys are added in M2-M5

## Files to Create

```
/
├── package.json
├── .env.example
├── docker-compose.yml
├── apps/
│   ├── api/
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── jest.config.ts
│   │   ├── src/
│   │   │   ├── main.ts
│   │   │   ├── app.module.ts
│   │   │   ├── common/
│   │   │   │   ├── filters/
│   │   │   │   │   └── http-exception.filter.ts
│   │   │   │   ├── interceptors/
│   │   │   │   │   └── response.interceptor.ts
│   │   │   │   └── pipes/
│   │   │   │       └── validation.pipe.ts
│   │   │   └── prisma/
│   │   │       ├── prisma.module.ts
│   │   │       └── prisma.service.ts
│   │   └── prisma/
│   │       └── schema.prisma
│   └── web/
│       ├── package.json
│       ├── tsconfig.json
│       ├── vitest.config.ts
│       ├── tailwind.config.ts
│       ├── next.config.ts
│       ├── src/
│       │   ├── app/
│       │   │   └── [locale]/
│       │   │       └── layout.tsx
│       │   ├── i18n.ts
│       │   ├── middleware.ts
│       │   ├── lib/
│       │   │   └── api-client.ts
│       │   └── styles/
│       │       └── globals.css
│       └── messages/
│           ├── en.json
│           └── ar.json
└── packages/
    └── api-client/
        └── index.ts
```
"""


M3_REQUIREMENTS_MD = """# Milestone 3: Projects

## Overview
- ID: milestone-3
- AC-Refs: AC-PROJ-001, AC-PROJ-002

## Description
Project CRUD + listing.

## Files to Create

```
apps/
├── api/
│   └── src/
│       └── projects/
│           ├── projects.module.ts
│           ├── projects.controller.ts
│           ├── projects.service.ts
│           └── dto/
│               └── create-project.dto.ts
└── web/
    └── src/
        └── app/
            └── [locale]/
                └── projects/
                    └── page.tsx
```
"""


SMOKE_STYLE_M1_REQUIREMENTS_MD = """# Milestone 1 - Platform Foundation

## In-Scope Deliverables

### Repository & Tooling
- Monorepo layout: `apps/api` (NestJS), `apps/web` (Next.js App Router),
  `packages/api-client` (generated TypeScript client), `prisma/`.
- `package.json` at root with workspace scripts.
- `.env.example` with `DATABASE_URL`.

### i18n / RTL machinery
- `locales/en/common.json` and `locales/ar/common.json` seeded.

## Merge Surfaces
`package.json`, `pnpm-workspace.yaml`, `apps/api/src/app.module.ts`,
`apps/api/src/main.ts`, `apps/web/next.config.mjs`,
`apps/web/src/app/layout.tsx`, `locales/en/common.json`,
`locales/ar/common.json`, `prisma/schema.prisma`, `docker-compose.yml`,
`.env.example`.
"""


MASTER_PLAN = {
    "milestones": [
        {
            "id": "milestone-1",
            "description": "Platform foundation scaffold.",
            "entities": [],
            "feature_refs": [],
            "ac_refs": [],
        },
        {
            "id": "milestone-2",
            "description": "User + auth.",
            "entities": ["User"],
            "feature_refs": ["F-AUTH"],
            "ac_refs": ["AC-AUTH-001"],
        },
        {
            "id": "milestone-3",
            "description": "Projects CRUD.",
            "entities": ["Project"],
            "feature_refs": ["F-PROJ"],
            "ac_refs": ["AC-PROJ-001", "AC-PROJ-002"],
        },
    ],
}


@pytest.fixture()
def m1_requirements_path(tmp_path):
    p = tmp_path / "m1_REQUIREMENTS.md"
    p.write_text(M1_REQUIREMENTS_MD, encoding="utf-8")
    return p


@pytest.fixture()
def m3_requirements_path(tmp_path):
    p = tmp_path / "m3_REQUIREMENTS.md"
    p.write_text(M3_REQUIREMENTS_MD, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test 1 — M1 scope filter excludes feature entities.
# ---------------------------------------------------------------------------

def test_m1_scope_filter_excludes_feature_entities(m1_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    assert isinstance(scope, MilestoneScope)
    assert scope.milestone_id == "milestone-1"
    assert scope.allowed_entities == []
    assert scope.allowed_feature_refs == []
    assert scope.allowed_ac_refs == []
    assert scope.allowed_file_globs, "M1 must have at least one allowed glob"


# ---------------------------------------------------------------------------
# Test 2 — M3 scope filter includes only Projects entities.
# ---------------------------------------------------------------------------

def test_m3_scope_filter_includes_only_projects_entities(m3_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-3",
        requirements_md_path=str(m3_requirements_path),
    )

    assert scope.allowed_entities == ["Project"]
    assert "Task" not in scope.allowed_entities
    assert "Comment" not in scope.allowed_entities
    assert "User" not in scope.allowed_entities
    assert scope.allowed_feature_refs == ["F-PROJ"]
    assert scope.allowed_ac_refs == ["AC-PROJ-001", "AC-PROJ-002"]


# ---------------------------------------------------------------------------
# Test 3 — Wave B prompt does not reference out-of-scope feature names.
# ---------------------------------------------------------------------------

def test_wave_b_prompt_does_not_reference_out_of_scope(m1_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    base_prompt = "Implement the backend scaffold for milestone-1."
    scoped = apply_scope_to_prompt(base_prompt, scope, wave="B")

    # Scope preamble must explicitly forbid M2+ entity/feature references.
    import re

    for forbidden in ("Task", "Kanban", "Comment"):
        # whole-word, case-sensitive
        assert not re.search(
            rf"(?<![A-Za-z0-9_]){forbidden}(?![A-Za-z0-9_])",
            scoped,
        ), (
            f"Wave B scope-applied prompt must not mention the forbidden entity "
            f"{forbidden!r}. Found it verbatim. Prompt:\n{scoped[:1500]}"
        )


# ---------------------------------------------------------------------------
# Test 4 — Wave D prompt for M1 does not reference feature pages.
# ---------------------------------------------------------------------------

def test_wave_d_prompt_for_m1_excludes_feature_pages(m1_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    base_prompt = "Implement the frontend scaffold for milestone-1."
    scoped = apply_scope_to_prompt(base_prompt, scope, wave="D")

    for forbidden in ("Task Detail", "Kanban", "Team Members", "User Profile"):
        assert forbidden not in scoped, (
            f"Wave D M1 scope-applied prompt must not mention {forbidden!r}"
        )


def test_wave_d_prompt_filters_non_frontend_scaffolded_files() -> None:
    prompt = build_wave_d_prompt(
        milestone=SimpleNamespace(id="milestone-1", title="Platform Foundation"),
        ir={},
        wave_c_artifact=None,
        scaffolded_files=[
            ".env.example",
            "apps/api/src/main.ts",
            "apps/web/src/app/[locale]/layout.tsx",
            "apps/web/src/lib/api/client.ts",
        ],
        config=None,
        existing_prompt_framework="[FRAMEWORK]",
        cwd=None,
    )

    assert "apps/web/src/app/[locale]/layout.tsx" in prompt
    assert "apps/web/src/lib/api/client.ts" in prompt
    assert "- .env.example" not in prompt
    assert "- apps/api/src/main.ts" not in prompt


def test_smoke_style_requirements_without_files_to_create_derive_scope_globs() -> None:
    globs = parse_files_to_create(SMOKE_STYLE_M1_REQUIREMENTS_MD)

    expected = {
        "apps/api/**",
        "apps/web/**",
        "packages/api-client/**",
        "prisma/**",
        "locales/**",
        "docker-compose.yml",
        ".env.example",
        "package.json",
        "pnpm-workspace.yaml",
    }
    assert expected.issubset(set(globs))

    scope = MilestoneScope(milestone_id="milestone-1", allowed_file_globs=globs)
    prompt = apply_scope_to_prompt("Implement platform foundation.", scope, wave="A")

    assert "nothing should be produced" not in prompt
    assert "apps/api/**" in prompt


def test_universal_scaffold_root_files_validator_exemption_when_globs_omit_them() -> None:
    """Wave B's `pnpm install` regenerates `pnpm-lock.yaml` and Wave B
    legitimately adds env vars to `.env.example`. Smoke
    ``v18 test runs/m1-hardening-smoke-20260425-171429`` SCOPE-VIOLATION-001'd
    Wave B for both files because the planner-authored REQUIREMENTS.md did
    not enumerate them. ``files_outside_scope`` must unconditionally exempt
    the universal scaffold-owned root files even when the milestone's
    declared globs do not list them.

    Validator-side only — the prompt-layer scope (``allowed_file_globs``)
    intentionally stays narrow so Wave A (architect) does not perceive
    a STACK-PATH-001 contradiction (smoke
    ``m1-hardening-smoke-20260425-174554``).
    """
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**", "apps/web/**"],
    )

    universal = [
        ".env.example",
        "docker-compose.yml",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
    ]
    assert files_outside_scope(universal, scope) == []

    # Out-of-scope writes that are NOT universal scaffold files still flag.
    mixed = ["pnpm-lock.yaml", "scripts/migrate.sh", "apps/api/src/main.ts"]
    assert files_outside_scope(mixed, scope) == ["scripts/migrate.sh"]


def test_universal_scaffold_files_not_in_prompt_layer_scope() -> None:
    """``parse_files_to_create`` must NOT inject universal scaffold root
    files into the prompt-layer scope. Wave A's architect prompt enumerates
    ``allowed_file_globs`` verbatim, and listing root-level files there
    triggers WAVE_A_CONTRACT_CONFLICT.md (smoke
    ``m1-hardening-smoke-20260425-174554``).
    """
    minimal_md = (
        "# Milestone 1 - Platform Foundation\n\n"
        "Scaffold the apps/api NestJS app shell.\n"
    )
    globs = parse_files_to_create(minimal_md)
    # The prompt-layer scope is REQUIREMENTS-derived: it should mention
    # ``apps/api/**`` (because the markdown referenced ``apps/api``) but
    # MUST NOT include scaffold operational files like the lockfile.
    assert "apps/api/**" in globs
    assert "pnpm-lock.yaml" not in globs


def test_post_wave_validator_exempts_per_milestone_e2e_tests_for_wave_e() -> None:
    """Smoke ``m1-hardening-smoke-20260425-175816`` Wave E failed
    SCOPE-VIOLATION-001 on ``e2e/tests/milestone-1/foundation.spec.ts``.
    Wave E's prompt hard-codes ``e2e/tests/<milestone_id>/`` as its output
    directory (see ``agents.build_wave_e_prompt``). The validator must
    exempt this prefix.
    """
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**", "apps/web/**"],
    )
    result = WaveResult(
        wave="E",
        success=True,
        files_created=[
            "e2e/tests/milestone-1/foundation.spec.ts",
            "e2e/tests/milestone-1/auth.spec.ts",
        ],
    )
    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="E",
        milestone_id="milestone-1",
        milestone_scope=scope,
    )
    assert result.success is True
    assert result.scope_violations == []

    # Other milestones' e2e dirs are NOT exempt for milestone-1's scope.
    scope_m2 = MilestoneScope(
        milestone_id="milestone-2",
        allowed_file_globs=["apps/api/**"],
    )
    bleed = files_outside_scope(["e2e/tests/milestone-1/x.spec.ts"], scope_m2)
    assert bleed == ["e2e/tests/milestone-1/x.spec.ts"]


def test_post_wave_validator_exempts_pnpm_lock_yaml_for_wave_b() -> None:
    """End-to-end regression for smoke ``m1-hardening-smoke-20260425-171429``
    where Wave B's ``pnpm install`` regenerated ``pnpm-lock.yaml`` and the
    write was rejected as out-of-scope. After the validator exempts
    universal scaffold files, the same simulated Wave B output succeeds.
    """
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**", "apps/web/**", "package.json"],
    )
    result = WaveResult(
        wave="B",
        success=True,
        files_modified=[
            ".env.example",
            "pnpm-lock.yaml",
            "apps/api/src/auth/auth.module.ts",
        ],
    )
    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="B",
        milestone_id="milestone-1",
        milestone_scope=scope,
    )
    assert result.success is True
    assert result.scope_violations == []


# ---------------------------------------------------------------------------
# Test 5 — Post-wave validator catches out-of-scope files.
# ---------------------------------------------------------------------------

def test_post_wave_validator_catches_out_of_scope_files(m1_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    files_created = [
        "apps/api/src/main.ts",  # in scope (M1 scaffold)
        "apps/api/src/projects/projects.controller.ts",  # M3 — out of scope
        "apps/api/src/tasks/tasks.service.ts",  # M4 — out of scope
    ]

    violations = files_outside_scope(files_created, scope)
    assert "apps/api/src/projects/projects.controller.ts" in violations
    assert "apps/api/src/tasks/tasks.service.ts" in violations
    assert "apps/api/src/main.ts" not in violations


def test_post_wave_scope_validation_fails_on_modified_backend_file_in_wave_d() -> None:
    result = WaveResult(
        wave="D",
        success=True,
        files_created=["apps/web/src/app/[locale]/layout.tsx"],
        files_modified=["apps/api/src/main.ts"],
    )

    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="D",
        milestone_id="milestone-1",
        milestone_scope=None,
    )

    assert result.success is False
    assert "apps/api/src/main.ts" in result.scope_violations
    assert result.error_message.startswith("SCOPE-VIOLATION-001")


def test_post_wave_scope_validation_fails_on_out_of_scope_modified_file(
    m1_requirements_path,
):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )
    result = WaveResult(
        wave="B",
        success=True,
        files_modified=["apps/api/src/projects/projects.controller.ts"],
    )

    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="B",
        milestone_id="milestone-1",
        milestone_scope=scope,
    )

    assert result.success is False
    assert "apps/api/src/projects/projects.controller.ts" in result.scope_violations
    assert result.error_message.startswith("SCOPE-VIOLATION-001")


# ---------------------------------------------------------------------------
# Test 6 — Post-wave validator ignores allowed files.
# ---------------------------------------------------------------------------

def test_wave_b_allows_frontend_foundation_contract_config_when_in_milestone_scope():
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**", "apps/web/**"],
    )
    result = WaveResult(
        wave="B",
        success=True,
        files_modified=[
            "apps/web/.env.example",
            "apps/web/openapi-ts.config.ts",
        ],
    )

    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="B",
        milestone_id="milestone-1",
        milestone_scope=scope,
    )

    assert result.success is True
    assert result.scope_violations == []


def test_wave_c_python_owned_outputs_bypass_milestone_scope():
    """Wave C is the deterministic Python OpenAPI generator; its file set
    is the source code of ``generate_openapi_contracts`` itself, not the
    milestone REQUIREMENTS.md scope. Smoke
    ``v18 test runs/m1-hardening-smoke-20260425-025111`` failed Wave C
    on ``contracts/openapi/current.json`` (and ``previous.json``)
    because the M1 REQUIREMENTS scope did not enumerate
    ``contracts/openapi/`` even though Wave C's contract_fidelity and
    client_fidelity were both ``canonical``. The post-wave milestone-scope
    arm must skip Wave C; ``find_forbidden_paths`` still runs (no-op
    for C, present for symmetry).
    """
    # Empty allowlist guarantees that ANY path would be rejected by
    # ``files_outside_scope``; if the Wave C bypass fires correctly,
    # nothing in scope_violations should reference these paths.
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**"],
    )
    result = WaveResult(
        wave="C",
        success=True,
        files_created=[
            "contracts/openapi/current.json",
            "contracts/openapi/milestone-1.json",
            "contracts/openapi/previous.json",
            "packages/api-client/index.ts",
            "packages/api-client/sdk.gen.ts",
            "packages/api-client/client.gen.ts",
            "packages/api-client/package.json",
        ],
    )

    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="C",
        milestone_id="milestone-1",
        milestone_scope=scope,
    )

    assert result.success is True
    assert result.scope_violations == []


def test_wave_b_milestone_scope_check_still_runs_after_wave_c_bypass():
    """Regression guard: the Wave C bypass must not accidentally relax
    the scope arm for B / D / D5 / E. Cross-check the symmetric case.
    """
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**"],
    )
    result = WaveResult(
        wave="B",
        success=True,
        files_created=["contracts/openapi/current.json"],
    )

    _apply_post_wave_scope_validation(
        wave_result=result,
        wave_letter="B",
        milestone_id="milestone-1",
        milestone_scope=scope,
    )

    assert result.success is False
    assert "contracts/openapi/current.json" in result.scope_violations


def test_post_wave_validator_ignores_allowed_files(m1_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    files_created = [
        "package.json",
        ".env.example",
        "docker-compose.yml",
        "apps/api/src/main.ts",
        "apps/api/src/app.module.ts",
        "apps/api/src/common/filters/http-exception.filter.ts",
        "apps/api/src/prisma/prisma.module.ts",
        "apps/api/prisma/schema.prisma",
        "apps/web/src/app/[locale]/layout.tsx",
        "apps/web/messages/en.json",
        "packages/api-client/index.ts",
    ]

    assert files_outside_scope(files_created, scope) == []


# ---------------------------------------------------------------------------
# Test 7 — IR filter removes out-of-scope entities and endpoints; feature flag
# controls prompt-layer enforcement (when False, apply_scope_to_prompt returns
# the prompt untouched).
# ---------------------------------------------------------------------------

def test_filter_ir_to_scope_and_feature_flag_behaviour(m1_requirements_path):
    scope = build_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    ir = {
        "entities": [
            {"name": "User"},
            {"name": "Project"},
            {"name": "Task"},
        ],
        "endpoints": [
            {"path": "/auth/login", "feature_ref": "F-AUTH"},
            {"path": "/projects", "feature_ref": "F-PROJ"},
        ],
        "translations": {
            "auth": {"login": "Log in"},
            "tasks": {"title": "Tasks"},
        },
    }

    filtered = filter_ir_to_scope(ir, scope)
    assert isinstance(filtered, FilteredIR)
    # M1 has no allowed entities/endpoints/translation namespaces.
    assert filtered.entities == []
    assert filtered.endpoints == []
    assert filtered.translations == {}

    # Feature flag off → prompt passthrough (pre-fix behaviour).
    cfg = AgentTeamConfig()
    cfg.v18.milestone_scope_enforcement = False
    base_prompt = "Implement backend scaffold."
    from agent_team_v15.milestone_scope import apply_scope_if_enabled

    assert apply_scope_if_enabled(base_prompt, scope, cfg, wave="B") == base_prompt

    # Feature flag on → preamble added.
    cfg.v18.milestone_scope_enforcement = True
    scoped = apply_scope_if_enabled(base_prompt, scope, cfg, wave="B")
    assert base_prompt in scoped
    assert scoped != base_prompt

    # WaveResult now carries scope_violations for post-wave validation wiring.
    wr = WaveResult(wave="B")
    assert hasattr(wr, "scope_violations")
    assert wr.scope_violations == []

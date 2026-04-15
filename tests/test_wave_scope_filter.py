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

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.milestone_scope import (
    MilestoneScope,
    apply_scope_to_prompt,
    build_scope_for_milestone,
    files_outside_scope,
    parse_files_to_create,
)
from agent_team_v15.scope_filter import FilteredIR, filter_ir_to_scope
from agent_team_v15.wave_executor import WaveResult


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


# ---------------------------------------------------------------------------
# Test 6 — Post-wave validator ignores allowed files.
# ---------------------------------------------------------------------------

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

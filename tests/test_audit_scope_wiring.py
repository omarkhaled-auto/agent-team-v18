"""C-01 fix-up: production caller wiring smoke tests.

Ensures ``build_auditor_agent_definitions`` forwards the AuditScope +
config into each auditor prompt when the v18 feature flag is on, and
preserves byte-identical legacy behaviour when scope is not supplied.
"""

from __future__ import annotations

import pytest

from agent_team_v15.audit_prompts import get_auditor_prompt
from agent_team_v15.audit_scope import audit_scope_for_milestone
from agent_team_v15.audit_team import build_auditor_agent_definitions
from agent_team_v15.config import AgentTeamConfig


M1_REQUIREMENTS_MD = """# Milestone 1: Platform Foundation

## Overview
- ID: milestone-1

## Description
Scaffold the NestJS + Next.js monorepo with shared infrastructure.

## Files to Create

```
/
├── package.json
├── docker-compose.yml
├── apps/
│   ├── api/
│   │   └── src/
│   │       ├── main.ts
│   │       └── app.module.ts
│   └── web/
│       └── src/
│           ├── i18n.ts
│           └── middleware.ts
└── packages/
    └── api-client/
        └── index.ts
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
    ],
}


@pytest.fixture()
def m1_scope(tmp_path):
    req = tmp_path / "m1_REQUIREMENTS.md"
    req.write_text(M1_REQUIREMENTS_MD, encoding="utf-8")
    return audit_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(req),
    )


# ---------------------------------------------------------------------------
# Test A — Flag ON: production caller surfaces scope preamble in auditor prompt.
# ---------------------------------------------------------------------------

def test_production_caller_applies_scope_when_flag_on(m1_scope):
    cfg = AgentTeamConfig()
    cfg.v18.audit_milestone_scoping = True

    agent_defs = build_auditor_agent_definitions(
        ["requirements"],
        scope=m1_scope,
        config=cfg,
    )

    assert "audit-requirements" in agent_defs
    prompt = agent_defs["audit-requirements"]["prompt"]
    assert "## Audit Scope — milestone-1" in prompt
    assert "Platform foundation scaffold." in prompt  # milestone description


# ---------------------------------------------------------------------------
# Test B — Flag OFF: production caller suppresses preamble even with scope.
# ---------------------------------------------------------------------------

def test_production_caller_suppresses_scope_when_flag_off(m1_scope):
    cfg = AgentTeamConfig()
    cfg.v18.audit_milestone_scoping = False

    agent_defs = build_auditor_agent_definitions(
        ["requirements"],
        scope=m1_scope,
        config=cfg,
    )

    prompt = agent_defs["audit-requirements"]["prompt"]
    assert "## Audit Scope" not in prompt
    assert "Platform foundation scaffold." not in prompt


# ---------------------------------------------------------------------------
# Test C — scope=None preserves byte-identical legacy behaviour.
# ---------------------------------------------------------------------------

def test_default_scope_none_matches_legacy_prompt():
    # No scope + no config = legacy path. The auditor prompt must equal
    # get_auditor_prompt's output exactly (allowing for the task_text
    # prefix added inside build_auditor_agent_definitions for the
    # requirements auditor only).
    requirements_path = "docs/req.md"
    legacy = get_auditor_prompt("technical", requirements_path=requirements_path)

    agent_defs = build_auditor_agent_definitions(
        ["technical"],
        requirements_path=requirements_path,
    )

    produced = agent_defs["audit-technical"]["prompt"]
    assert produced == legacy, (
        "Default scope=None must be byte-identical to the pre-C-01 prompt"
    )

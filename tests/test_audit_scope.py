"""C-01: auditor milestone-scope unit tests.

Verifies that the audit layer restricts its evaluation target to the
current milestone's allowed_file_globs, and that findings on files
outside that scope are consolidated into a ``scope_violation`` category
that does NOT deduct score.
"""

from __future__ import annotations

import pytest

from agent_team_v15.audit_models import (
    AuditFinding,
    AuditReport,
    AuditScore,
    build_report,
)
from agent_team_v15.audit_scope import (
    AuditScope,
    audit_scope_for_milestone,
    build_scoped_audit_prompt,
    partition_findings_by_scope,
    scope_violation_findings,
)
from agent_team_v15.milestone_scope import MilestoneScope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


M1_REQUIREMENTS_MD = """# Milestone 1: Platform Foundation

## Overview
- ID: milestone-1

## Description
Scaffold the NestJS + Next.js monorepo.

## Files to Create

```
/
├── package.json
├── .env.example
├── docker-compose.yml
├── apps/
│   ├── api/
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── main.ts
│   │   │   ├── app.module.ts
│   │   │   ├── common/
│   │   │   │   ├── filters/
│   │   │   │   │   └── http-exception.filter.ts
│   │   │   │   └── interceptors/
│   │   │   │       └── response.interceptor.ts
│   │   │   └── prisma/
│   │   │       ├── prisma.module.ts
│   │   │       └── prisma.service.ts
│   │   └── prisma/
│   │       └── schema.prisma
│   └── web/
│       ├── package.json
│       ├── src/
│       │   ├── app/
│       │   │   └── [locale]/
│       │   │       └── layout.tsx
│       │   └── i18n.ts
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
│           └── projects.service.ts
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
        {"id": "milestone-1", "description": "Foundation scaffold.", "entities": [], "feature_refs": []},
        {"id": "milestone-3", "description": "Projects.", "entities": ["Project"], "feature_refs": ["F-PROJ"]},
    ],
}


@pytest.fixture()
def m1_requirements_path(tmp_path):
    p = tmp_path / "milestones" / "milestone-1" / "REQUIREMENTS.md"
    p.parent.mkdir(parents=True)
    p.write_text(M1_REQUIREMENTS_MD, encoding="utf-8")
    return p


@pytest.fixture()
def m3_requirements_path(tmp_path):
    p = tmp_path / "milestones" / "milestone-3" / "REQUIREMENTS.md"
    p.parent.mkdir(parents=True)
    p.write_text(M3_REQUIREMENTS_MD, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test 1 — M1 scope excludes feature file globs.
# ---------------------------------------------------------------------------

def test_m1_scope_has_no_feature_file_globs(m1_requirements_path):
    scope = audit_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    assert isinstance(scope, AuditScope)
    assert scope.milestone_id == "milestone-1"

    joined = " ".join(scope.allowed_file_globs)
    for forbidden in (
        "apps/api/src/projects",
        "apps/api/src/tasks",
        "apps/api/src/comments",
        "apps/api/src/users",
    ):
        assert forbidden not in joined, (
            f"M1 audit scope must not list {forbidden!r} in allowed globs; got: {joined}"
        )


# ---------------------------------------------------------------------------
# Test 2 — M1 scope includes docker-compose + scaffold files.
# ---------------------------------------------------------------------------

def test_m1_scope_includes_docker_compose_and_scaffold(m1_requirements_path):
    scope = audit_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    assert "docker-compose.yml" in scope.allowed_file_globs
    assert "apps/api/src/main.ts" in scope.allowed_file_globs


# ---------------------------------------------------------------------------
# Test 3 — M3 scope includes Projects files.
# ---------------------------------------------------------------------------

def test_m3_scope_includes_projects_files(m3_requirements_path):
    scope = audit_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-3",
        requirements_md_path=str(m3_requirements_path),
    )

    assert any("projects" in g for g in scope.allowed_file_globs)
    # Some glob variant that matches apps/api/src/projects/projects.controller.ts
    from agent_team_v15.milestone_scope import file_matches_any_glob

    assert file_matches_any_glob(
        "apps/api/src/projects/projects.controller.ts",
        scope.allowed_file_globs,
    )


# ---------------------------------------------------------------------------
# Test 4 — scope_violation findings do not deduct score.
# ---------------------------------------------------------------------------

def test_scope_violation_findings_do_not_deduct_score(m1_requirements_path):
    scope = audit_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    # Build some baseline PASS findings so the score ratio is non-trivial.
    passing = [
        AuditFinding(
            finding_id=f"PASS-{i}",
            auditor="requirements",
            requirement_id=f"REQ-PASS-{i}",
            verdict="PASS",
            severity="INFO",
            summary=f"Verified requirement {i}",
            evidence=[f"apps/api/src/main.ts:{i + 100} -- verified"],
        )
        for i in range(10)
    ]
    # Build 5 in-scope FAIL findings + 5 out-of-scope findings on M3 paths.
    in_scope = [
        AuditFinding(
            finding_id=f"IN-{i}",
            auditor="requirements",
            requirement_id=f"REQ-IN-{i}",
            verdict="FAIL",
            severity="HIGH",
            summary=f"In-scope failure {i}",
            evidence=[f"apps/api/src/main.ts:{i} -- failure"],
        )
        for i in range(5)
    ]
    out_of_scope_files = [
        "apps/api/src/projects/projects.controller.ts",
        "apps/api/src/tasks/tasks.service.ts",
        "apps/api/src/comments/comments.module.ts",
        "apps/api/src/users/users.controller.ts",
        "apps/web/src/app/[locale]/tasks/page.tsx",
    ]
    out_of_scope = [
        AuditFinding(
            finding_id=f"OUT-{i}",
            auditor="requirements",
            requirement_id=f"REQ-OUT-{i}",
            verdict="FAIL",
            severity="HIGH",
            summary=f"Out-of-scope failure {i}",
            evidence=[f"{path}:{i} -- failure"],
        )
        for i, path in enumerate(out_of_scope_files)
    ]

    baseline_findings = passing + in_scope + out_of_scope
    baseline = build_report(
        audit_id="baseline",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=baseline_findings,
    )

    scoped_findings = partition_findings_by_scope(baseline_findings, scope)
    # passing findings attach to apps/api/src/main.ts (in-scope) -> 10 in-scope.
    assert len(scoped_findings.in_scope) == 15
    assert len(scoped_findings.out_of_scope) == 5

    # The scope_violation consolidated findings must be produced and must
    # NOT be severity FAIL verdicts that count toward the score.
    scope_findings = scope_violation_findings(scoped_findings.out_of_scope, scope)
    for f in scope_findings:
        assert f.severity == "HIGH"
        # Verdict INFO keeps them out of the pass/fail scoring math.
        assert f.verdict == "INFO"

    # Rebuild the report with only in-scope + consolidated scope_violation
    # findings. Compare score to the baseline: more findings pre-fix
    # (10 FAIL) vs scoped post-fix (5 FAIL + few consolidated).
    scoped_report = build_report(
        audit_id="scoped",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=scoped_findings.in_scope + scope_findings,
    )

    # Baseline: 10 PASS + 10 FAIL requirements -> 10/20 = 50.0.
    # Scoped: 10 PASS + 5 FAIL (+ INFO scope_violation that doesn't count) -> 10/15 = 66.7.
    assert baseline.score.score == pytest.approx(50.0, abs=0.1)
    assert scoped_report.score.score == pytest.approx(66.7, abs=0.1)
    assert scoped_report.score.score > baseline.score.score


# ---------------------------------------------------------------------------
# Test 5 — audit prompt excludes out-of-scope files.
# ---------------------------------------------------------------------------

def test_audit_prompt_excludes_out_of_scope_files(m1_requirements_path):
    scope = audit_scope_for_milestone(
        master_plan=MASTER_PLAN,
        milestone_id="milestone-1",
        requirements_md_path=str(m1_requirements_path),
    )

    base_prompt = (
        "You are the REQUIREMENTS AUDITOR. Evaluate the codebase against "
        "the spec and output findings."
    )
    scoped_prompt = build_scoped_audit_prompt(base_prompt, scope)

    # The scoped prompt's evaluation target list must not contain out-of-
    # scope directories.
    assert "apps/api/src/projects" not in scoped_prompt
    assert "apps/api/src/tasks" not in scoped_prompt
    assert "apps/api/src/comments" not in scoped_prompt
    assert "apps/api/src/users" not in scoped_prompt

    # The original prompt body must still be present (composition, not
    # replacement).
    assert base_prompt in scoped_prompt

# Phase H2bc Discovery Citations

## Ownership

- Policy file already present on this branch:
  `docs/SCAFFOLD_OWNERSHIP.md:1-87`
- Shared parser:
  `src/agent_team_v15/scaffold_runner.py:147-171`
  `src/agent_team_v15/scaffold_runner.py:174-229`
- Check C loader and forbidden-write check:
  `src/agent_team_v15/ownership_enforcer.py:206-238`
  `src/agent_team_v15/ownership_enforcer.py:334-375`
- Spec reconciler load site:
  `src/agent_team_v15/wave_executor.py:983-1027`
- Reconciler consumer:
  `src/agent_team_v15/milestone_spec_reconciler.py:72-208`
- Scaffold verifier load site:
  `src/agent_team_v15/wave_executor.py:1030-1077`
- Scaffold verifier core:
  `src/agent_team_v15/scaffold_verifier.py:65-227`
- Regex dependency on raw `- path:` lines:
  `src/agent_team_v15/wave_a_schema_validator.py:860-883`
- Existing contract-validation soft invariant:
  `src/agent_team_v15/scaffold_runner.py:338-380`
- Current ownership-related config flags:
  `src/agent_team_v15/config.py:922-941`
  `src/agent_team_v15/config.py:2737-2757`
  `src/agent_team_v15/config.py:3013-3019`

## Smoke Evidence

- Triple skip from missing policy in worktree:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:29-51`
- Dockerfile miss and policy cascade:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:165-216`
- N-10 crash:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:222-236`
- Convergence 0/0:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:240-266`
- Smoke summary on ownership/doc gap:
  `v18 test runs/phase-final-smoke-20260419-205237/SMOKE_12_REPORT.md:38-43`
- Smoke summary on missing idioms cache:
  `v18 test runs/phase-final-smoke-20260419-205237/SMOKE_12_REPORT.md:57`

## REQUIREMENTS Shape

- M1 Docker/env section:
  `v18 test runs/phase-final-smoke-20260419-205237/.agent-team/milestones/milestone-1/REQUIREMENTS.md:81-88`
- M1 audit review log table:
  `v18 test runs/phase-final-smoke-20260419-205237/.agent-team/milestones/milestone-1/REQUIREMENTS.md:146-175`

## N-10

- Scanner merge caller:
  `src/agent_team_v15/cli.py:6288-6310`
- Merge implementation:
  `src/agent_team_v15/forbidden_content_scanner.py:402-440`
- Scorer schema declares count maps:
  `src/agent_team_v15/audit_prompts.py:1294-1317`
- Canonical `AuditReport.from_json()` preserves scorer-side maps verbatim:
  `src/agent_team_v15/audit_models.py:439-456`

## Convergence

- Aggregate report:
  `src/agent_team_v15/milestone_manager.py:1173-1245`
- Checkbox-only count parser:
  `src/agent_team_v15/milestone_manager.py:1444-1455`
- Single-milestone health path:
  `src/agent_team_v15/milestone_manager.py:1548-1601`
- Shared regex helpers in config:
  `src/agent_team_v15/config.py:1719-1743`

## Audit Scope Persistence

- Audit report schema includes `scope`:
  `src/agent_team_v15/audit_models.py:247-322`
- Scope rebuild currently nested inside evidence-gating loop:
  `src/agent_team_v15/cli.py:1070-1204`
- Final audit-loop write:
  `src/agent_team_v15/cli.py:7189-7194`

## Idioms Cache

- Wave prefetch enablement:
  `src/agent_team_v15/cli.py:2170-2185`
- Query map and cache helper:
  `src/agent_team_v15/cli.py:2188-2318`
- Wrapper prompt builder in one execution path:
  `src/agent_team_v15/cli.py:4262-4281`
- Wrapper prompt builder in the other execution path:
  `src/agent_team_v15/cli.py:4897-4915`
- Prompt emission site:
  `src/agent_team_v15/agents.py:8515-8522`
- Existing N-17 tests:
  `tests/test_n17_mcp_prefetch.py:72-200`

## Wave B Prompt / Deliverables

- Wave B prompt:
  `src/agent_team_v15/agents.py:8445-8717`
- Backend task manifest truncation:
  `src/agent_team_v15/agents.py:7862-7879`
- Requirements excerpt truncation:
  `src/agent_team_v15/agents.py:7601-7616`
- Scaffolded files formatter truncation:
  `src/agent_team_v15/agents.py:7251-7255`

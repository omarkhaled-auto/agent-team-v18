# Phase H2bc Small Bugs Triage

## C1: N-10 forbidden-content scanner

### Observed failure

- Smoke log:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:222-236`

### Root cause

- `cli.py` loads scorer-shaped `AUDIT_REPORT.json` and then merges deterministic findings:
  `src/agent_team_v15/cli.py:6288-6310`
- `merge_findings_into_report()` assumes `by_severity`, `by_file`, and `by_requirement` are index lists:
  `src/agent_team_v15/forbidden_content_scanner.py:424-440`
- Scorer schema defines those maps as integer counts:
  `src/agent_team_v15/audit_prompts.py:1294-1317`
- `AuditReport.from_json()` preserves those maps verbatim:
  `src/agent_team_v15/audit_models.py:439-456`

### Fix

- Normalize the report indices before merging
- Rebuild index maps from `report.findings` when the loaded maps contain counts rather than lists

### Expected size

- Small

## C2: Convergence aggregation 0/0

### Observed failure

- Smoke log:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:240-266`

### Root cause

- `MilestoneManager._parse_requirements_counts()` only counts checkbox lines:
  `src/agent_team_v15/milestone_manager.py:1444-1446`
- `MilestoneManager._parse_max_review_cycles()` only reads `(review_cycles: N)` markers:
  `src/agent_team_v15/milestone_manager.py:1449-1455`
- Smoke REQUIREMENTS for M1 uses an audit review log table, not checkbox items:
  `v18 test runs/phase-final-smoke-20260419-205237/.agent-team/milestones/milestone-1/REQUIREMENTS.md:146-175`

### Decision

Do not force REQUIREMENTS emission back to checkbox format in H2bc. The emitted table is already present in smoke artifacts and the smaller, safer fix is to make the aggregator understand both shapes.

### Fix

- Preserve current checkbox parsing for legacy docs
- Add fallback parsing for the markdown audit review log table
- Treat:
  - `PASS` as checked
  - `FAIL` and `PARTIAL` as unchecked
  - `GENERAL` as non-requirement metadata and exclude it from totals

### Expected size

- Small to medium, still localized to `milestone_manager.py`

## C3: `AUDIT_REPORT.json.scope` missing

### Observed failure

- Exit criterion and smoke summary:
  `PHASE_FINAL_EXIT_CRITERIA.md:28`
  `v18 test runs/phase-final-smoke-20260419-205237/SMOKE_12_REPORT.md:38-43`

### Root cause

- Canonical `AuditReport.to_json()` already includes `scope`:
  `src/agent_team_v15/audit_models.py:296-322`
- Real caller bug is in `_apply_evidence_gating_to_audit_report()`:
  `src/agent_team_v15/cli.py:1070-1204`
- Scope partitioning and rebuild are nested inside the per-requirement evidence-downgrade loop, so reports with no evidence downgrade never rebuild with a populated `scope`

### Fix

- Move scope partitioning/rebuild outside the loop
- Preserve `extras`
- Persist the normalized report on the same caller path so `AUDIT_REPORT.json` on disk always carries `scope`, even when it is an empty dict

### Expected size

- Small

## C4: Framework idioms cache

### Observed failure

- Smoke config enabled the feature:
  `v18 test runs/phase-final-smoke-20260419-205237/config.yaml:47-50,69-70`
- Smoke still reported no cache file:
  `v18 test runs/phase-final-smoke-20260419-205237/SMOKE_12_REPORT.md:57`

### Likely failure surface

- `_prefetch_framework_idioms()` knows how to write the cache:
  `src/agent_team_v15/cli.py:2222-2318`
- The execution wrappers inject `mcp_doc_context` just before prompt build:
  `src/agent_team_v15/cli.py:4262-4281`
  `src/agent_team_v15/cli.py:4897-4915`

### Fix

- Preserve any caller-supplied `mcp_doc_context` instead of replacing it
- Guarantee cache persistence from the wrapper path when non-empty idioms text exists
- Add a wrapper-level regression test that asserts `.agent-team/framework_idioms_cache.json` exists after prompt construction on the execution path

### Expected size

- Small

## C5: Wave B scaffold deliverable enumeration

### Observed failure

- Smoke Dockerfile miss:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:165-216`

### Root cause

- The task manifest truncates scaffold hints to 10 files:
  `src/agent_team_v15/agents.py:7862-7879`
- The inline requirements excerpt only loads the first 40 non-empty lines:
  `src/agent_team_v15/agents.py:7601-7616`
- The Docker/env deliverables live later in the REQUIREMENTS doc:
  `v18 test runs/phase-final-smoke-20260419-205237/.agent-team/milestones/milestone-1/REQUIREMENTS.md:81-88`

### Fix

- Add a dedicated `[SCAFFOLD DELIVERABLES VERIFICATION]` block to `build_wave_b_prompt()`
- Read the full REQUIREMENTS document from the milestone path
- Extract and list critical deliverables explicitly, at minimum:
  - `apps/api/Dockerfile`
  - `apps/web/Dockerfile`
  - `docker-compose.yml`
  - `.env.example`
  - `apps/api/.env.example`

### Expected size

- Small

## No-HALT Call

All five bugs look localized and phase-appropriate. None currently require scope review.

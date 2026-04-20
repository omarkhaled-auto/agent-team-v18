# Phase H2bc Architecture Report

## Summary

This branch already contains `docs/SCAFFOLD_OWNERSHIP.md` at `4a8a80d` time. The smoke failure was not caused by the source repo lacking the file; it was caused by runtime readers resolving the contract relative to the generated worktree, where `docs/` was absent. The parser itself is already unified in `src/agent_team_v15/scaffold_runner.py:174-229`.

H2bc therefore needs:

1. A unified ownership-policy resolution path that can load the checked-in policy from repo source when the generated worktree lacks `docs/SCAFFOLD_OWNERSHIP.md`.
2. A fail-loud flag so missing policy becomes a hard error when explicitly required.
3. A scaffold-verifier extension for policy-listed required deliverables.
4. Five small runtime fixes: N-10 merge normalization, convergence parsing for audit-log-table REQUIREMENTS, scope persistence on the real audit caller path, guaranteed idioms-cache emission on the wrapper path, and explicit scaffold-deliverable enumeration in Wave B prompts.

## Scope B: Ownership

### Shared parser

- Canonical parser: `src/agent_team_v15/scaffold_runner.py:174-229`
- Format expected today: Markdown prose plus one or more fenced `yaml` blocks, each containing a YAML list of rows with required keys `path`, `owner`, `optional`; optional keys `emits_stub`, `audit_expected`, `notes`
- `notes:` is intentionally stripped before YAML parse at `src/agent_team_v15/scaffold_runner.py:147-171`
- `src/agent_team_v15/wave_a_schema_validator.py:860-883` still regex-scans raw `- path:` lines, so the policy must retain that textual shape

### Current consumers

- Check C / ownership enforcer:
  `src/agent_team_v15/ownership_enforcer.py:206-238`, `:334-375`
- Spec reconciler load site:
  `src/agent_team_v15/wave_executor.py:983-1027`
- Scaffold verifier load site:
  `src/agent_team_v15/wave_executor.py:1051-1077`

### Real failure mode

- The checked-in file exists at `docs/SCAFFOLD_OWNERSHIP.md:1-87`
- Smoke workspace lacked a `docs/` directory entirely:
  `v18 test runs/phase-final-smoke-20260419-205237` listing
- Smoke logged all three readers skipping:
  `v18 test runs/phase-final-smoke-20260419-205237/findings-running.md:29-51`

### Implementation direction

- Keep one parser in `scaffold_runner.py`
- Add one resolver/helper in the same module that tries:
  1. `<workspace>/docs/SCAFFOLD_OWNERSHIP.md`
  2. repo-root `docs/SCAFFOLD_OWNERSHIP.md` resolved from module location
- Thread `v18.ownership_policy_required: bool = False` through:
  - `ownership_enforcer._load_scaffold_owned_paths`
  - `wave_executor._maybe_run_spec_reconciliation`
  - `wave_executor._maybe_run_scaffold_verifier`
  - `scaffold_runner._maybe_validate_ownership`
- When the flag is `True`, raise a dedicated `OwnershipPolicyMissingError`
- When the flag is `False`, preserve WARN-and-skip behavior

### Policy document design

- Do not replace the file format
- Update the existing `docs/SCAFFOLD_OWNERSHIP.md` in place
- Add a small H2bc header/revision note and a policy-listed deliverables section that the verifier can read deterministically
- Keep the policy as Markdown with fenced YAML blocks so all current consumers remain compatible

### Deliverable verification

- Extend `src/agent_team_v15/scaffold_verifier.py:65-227`
- Add a policy-driven check for required deliverables, emitting one structured finding when a policy-listed path is absent
- Run this inside the scaffold verifier before later live-probe failures make the miss expensive

## Scope C: Small Bugs

### C1: N-10 merge crash

- Caller: `src/agent_team_v15/cli.py:6288-6310`
- Crash site: `src/agent_team_v15/forbidden_content_scanner.py:424-440`
- Root cause: scorer-shaped `AUDIT_REPORT.json` stores `by_severity`, `by_file`, and `by_requirement` as integer counts, while merge logic assumes list-of-index maps
- Fix direction: normalize/rebuild index maps before appending scanner findings

### C2: Convergence 0/0

- Aggregator: `src/agent_team_v15/milestone_manager.py:1173-1245`
- Parser used by single-milestone health: `:1444-1455`, `:1548-1601`
- Current parser only counts checkbox lines
- Smoke M1 REQUIREMENTS is an audit-log table with `review_cycles` markers, not checkbox items:
  `v18 test runs/phase-final-smoke-20260419-205237/.agent-team/milestones/milestone-1/REQUIREMENTS.md:146-175`
- Fix direction: keep checkbox parsing for legacy docs, add fallback parsing for the audit review log table

### C3: `AUDIT_REPORT.json.scope` missing

- Scope payload is built in the real caller path at `src/agent_team_v15/cli.py:1137-1200`
- Bug: scope rebuild/persistence currently sits inside the evidence-gating loop, so it only runs when a requirement is downgraded by evidence
- Fix direction: move scope partitioning and rebuild outside the per-requirement downgrade loop, then persist the normalized report on the same caller path

### C4: Framework idioms cache

- Fetch/write helper: `src/agent_team_v15/cli.py:2222-2318`
- Wrapper path used before wave execution: `src/agent_team_v15/cli.py:4262-4281`, mirrored at `:4897-4915`
- Smoke config had all relevant flags on:
  `v18 test runs/phase-final-smoke-20260419-205237/config.yaml:47-50,69-70`
- Smoke still reported cache absence:
  `v18 test runs/phase-final-smoke-20260419-205237/SMOKE_12_REPORT.md:57`
- Fix direction: make the wrapper path preserve any existing `mcp_doc_context`, and guarantee cache persistence when non-empty idioms text is available

### C5: Wave B scaffold deliverables

- Prompt builder: `src/agent_team_v15/agents.py:8445-8717`
- Current manifest truncates scaffolded file hints to 10 entries:
  `src/agent_team_v15/agents.py:7862-7879`
- Current requirements excerpt only reads the first 40 non-empty lines:
  `src/agent_team_v15/agents.py:7601-7616`
- M1 Docker/env requirements sit much later in the file:
  `v18 test runs/phase-final-smoke-20260419-205237/.agent-team/milestones/milestone-1/REQUIREMENTS.md:81-88`
- Fix direction: load the full REQUIREMENTS document, extract critical scaffold deliverables, and inject a dedicated `[SCAFFOLD DELIVERABLES VERIFICATION]` block into Wave B

## HALT Assessment

- No HALT needed for size: current policy file already exists and can be updated rather than authored from scratch
- No parser-compatibility HALT: there is already one parser
- No >100 LOC verifier HALT expected: required-deliverable verification can be added as a focused policy-driven extension
- No small-bug HALT identified: all five issues look localized

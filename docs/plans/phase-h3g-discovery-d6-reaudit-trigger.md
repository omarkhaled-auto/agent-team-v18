# Phase H3g Discovery - D6 Re-Audit Trigger

## Verdict

Proceed. No HALT.

## Landmarks

- `src/agent_team_v15/cli.py:5522-5567`
- `src/agent_team_v15/cli.py:5770-5798`
- `src/agent_team_v15/cli.py:6125-6135`
- `src/agent_team_v15/cli.py:7059-7299`
- `src/agent_team_v15/audit_team.py:93-133`

## Key Finding

`_run_audit_loop()` is not the failing component.

A local harness against `_run_audit_loop()` with a smoke-shaped scorer report and `max_reaudit_cycles=2` correctly ran cycle 2. The low-score trigger inside the audit loop is intact.

## Root Cause

The PRD milestone path short-circuits before the per-milestone audit loop:

- On failed milestone health gate, `cli.py:5553-5567` marks the milestone FAILED and executes `continue`.
- That bypasses the per-milestone `_run_audit_loop()` block at `cli.py:5770-5792`.
- Later, the pipeline still runs the final cross-milestone/interface audit via `_run_milestone_audit()` directly at `cli.py:6125-6135`.
- That later audit is single-cycle and has no fix / re-audit path.

So the smoke's low score was produced by a different audit path than the one that can re-audit.

## Non-Root-Cause Observations

- `audit_fix_rounds` in `RunState` is currently unwired and cannot be trusted as proof that re-audit did or did not run.
- `AuditReport.from_json()` permissively reads scorer reports but scorer-style `overall_score` still collapses to `score=0.0` inside the canonical object unless `score` is present. That is a separate parsing/reporting quality issue, not the re-audit trigger itself.

## Recommended Fix Shape

Add a flag-gated failed-milestone audit path in `cli.py`:

- `reaudit_trigger_fix_enabled: bool = False`

When the flag is on and the milestone is about to fail the health gate:

1. Run the per-milestone `_run_audit_loop()` before the failure `continue`.
2. Preserve the milestone FAILED outcome unless some separate caller changes that behavior explicitly.
3. Leave the existing final standard/interface audit path unchanged.

This is a bounded control-flow fix, not a new audit subsystem.

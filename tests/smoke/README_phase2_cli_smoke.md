# Phase 2 CLI Smoke

Run the deterministic Phase 2 smoke with:

```bash
PYTHONPATH=src python tests/smoke/run_phase2_cli_smoke.py
```

What it does:

- copies `tests/fixtures/phase2_cli_smoke/workspace` to a temporary run directory
- installs the fixture's local `typescript` dependency if needed
- runs the real milestone path through `agent_team_v15.cli._run_prd_milestones()`
- keeps Phase 2 flags fixed to `execution_mode=wave`, `live_endpoint_check=false`, `evidence_mode=disabled`, and `git_isolation=false`
- uses a deterministic no-op SDK client so compile checks, Wave C contract generation, artifact extraction, Wave E finalization, and post-milestone health can be reproduced without external model variance

Expected result:

- wave artifacts and telemetry exist for `A`, `B`, `C`, and `E`
- `contracts/openapi/current.json` and `contracts/openapi/milestone-1.json` exist
- `REQUIREMENTS.md` has only checked items with `review_cycles` markers
- `TASKS.md` uses canonical `- Status: COMPLETE` lines
- `MilestoneManager.check_milestone_health("milestone-1")` returns `healthy`
- no evidence directory is created in this Phase 2 mode

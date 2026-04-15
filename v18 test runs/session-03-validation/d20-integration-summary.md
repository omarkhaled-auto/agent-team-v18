# D-20 — M1 startup-AC probe integration summary

## Module

New file: `src/agent_team_v15/m1_startup_probe.py` (~230 LOC).

Public surface:
- `run_m1_startup_probe(workspace: Path) -> dict[str, dict[str, Any]]` — executes the five M1 startup ACs (`npm install`, `docker compose up -d postgres`, `npx prisma migrate dev --name init`, `npm run test:api`, `npm run test:web`) in order, always runs `docker compose down` in a `finally` block, and returns structured results keyed by probe name (plus `compose_down` teardown).
- Internals:
  - `_run(cmd, *, cwd, timeout, env=None)` — the single subprocess seam. Catches `TimeoutExpired` + `FileNotFoundError`/`OSError`, returns structured `status`/`exit_code`/`stdout_tail`/`stderr_tail`/`duration_s` dicts. This is the seam unit tests mock.
  - `_compose_command()` — prefers modern `docker compose` (plugin); falls back to legacy `docker-compose` when `docker compose version` is unavailable. Resolves the Windows caveat called out in `docs/plans/2026-04-15-d-20-m1-startup-ac-probe.md` §7.
  - `_tail(blob)` — trims captured stdout/stderr to the last 1 KB so telemetry doesn't balloon on `npm install` output.

## AuditReport field

Added `acceptance_tests: dict[str, Any]` to `AuditReport` (audit_models.py line 234 in the new file). Round-tripped through `to_json`/`from_json`. `acceptance_tests` is added to `_AUDIT_REPORT_KNOWN_KEYS` so it is not double-captured on `extras`.

## Integration in `_run_milestone_audit`

Location: `src/agent_team_v15/cli.py`, inside `_run_milestone_audit` after the `_apply_evidence_gating_to_audit_report` call (previously ~line 5396). The new helper `_maybe_run_m1_startup_probe(report, milestone_id, milestone_template, audit_dir, config)` was added immediately after `_run_milestone_audit` (new function following line 5407 onward).

Gate order in `_maybe_run_m1_startup_probe`:
1. `config.v18.m1_startup_probe` is truthy (default True).
2. `milestone_id` provided AND `milestone_template == "full_stack"`.
3. `MASTER_PLAN.json` readable at `<audit_dir>/MASTER_PLAN.json`.
4. That milestone's `complexity_estimate.entity_count == 0` (infrastructure milestone).

When gates pass, `run_m1_startup_probe(workspace)` is invoked with `workspace = Path(audit_dir).parent`. Results land on `report.acceptance_tests["m1_startup_probe"]`. Any probe with `status` in `{"fail", "timeout", "error"}` sets `report.extras["verdict"] = "FAIL"` regardless of finding count — honoring plan §3c.

The integration is wrapped in its own `try/except` in `_run_milestone_audit` so a probe-module bug cannot break audit-report parsing.

## Feature flag

Added `m1_startup_probe: bool = True` to `V18Config` (config.py line 825 in the new file). Also wired through the YAML loader (config.py line 2416+).

## Test coverage

`tests/test_m1_startup_probe.py` — 5 tests, all mocking subprocess via `unittest.mock.patch`:

1. `test_happy_path_all_probes_pass` — mocks `m1_startup_probe._run` to always return pass; all 5 probes + teardown recorded.
2. `test_npm_install_fail_flips_verdict_to_fail` — exercises `_maybe_run_m1_startup_probe`; asserts a failed probe flips `extras["verdict"]` to "FAIL".
3. `test_non_infrastructure_milestone_skipped` — entity_count=2 short-circuits; `run_m1_startup_probe` never called; `acceptance_tests` empty.
4. `test_timeout_recorded_without_crashing` — mocks the real `subprocess.run` to raise `TimeoutExpired`; verifies `_run`'s exception handler records `status="timeout"`.
5. `test_teardown_runs_even_when_probe_raises_midway` — mocks `_run` to raise `RuntimeError` on `compose_up`; verifies `compose_down` is still invoked in the `finally` block (exception propagates, which is acceptable — teardown guarantee is the invariant).

**Zero real subprocess invocations.** All five tests mock either `m1_startup_probe._run` or `m1_startup_probe.subprocess.run`.

## What NOT to infer from these tests

- Unit tests prove the control-flow seams. They do NOT prove the real `npm install` / `docker compose` / `prisma migrate` commands pass in a freshly scaffolded workspace. That end-to-end proof is Session 6's Gate A smoke. Per memory `feedback_verification_before_completion`: the probe is "mechanism validated in unit tests", not "end-to-end observed."

- `_compose_command()` itself is not unit-tested (it invokes `subprocess.run` to detect binaries). In tests we always `patch.object(m1_startup_probe, "_compose_command", return_value=["docker", "compose"])` to keep test outcomes deterministic. Its real behavior is exercised by Gate A.

# Pre-Rerun Cleanup Report (2026-04-14)

## Summary

All three open items were closed on `bug-9-tier-2-stack-contract-validator`, the full `pytest tests/ -v` suite is green, and `docs/plans/2026-04-14-smoke-test-rerun-handoff.md` now reflects Tier 2 plus the cleanup closures. The smoke test itself was not launched in this session.

## Bug #2 fix

`src/agent_team_v15/milestone_manager.py` now accepts the legacy hyphenated shorthand with:

```python
_short_form = re.compile(r"^[Mm]-?(\d+)$")
```

Before this change, `_parse_deps("m-1")` failed normalization and the dependency was dropped by the defensive filter. After the change, `m-1` normalizes to `milestone-1` and survives the same filter path.

Verification:

- `tests/test_milestone_manager.py::TestParseDeps` -> `16 passed`
- Added regression coverage for mixed short forms and prose-bullet filtering

Session commit:

- `b57cb43` - `fix(plan-validator): accept hyphenated m-N shorthand in _parse_deps regression`

## Bug #8 fix

`src/agent_team_v15/scaffold_runner.py` now includes `_ensure_package_json_openapi_script(project_root: Path) -> bool`, called from `_scaffold_nestjs()`. The helper is idempotent and ensures all three required entries exist:

- `scripts.generate-openapi = "tsx scripts/generate-openapi.ts"`
- `devDependencies.tsx = "^4.7.0"`
- `dependencies.@nestjs/swagger = "^7.0.0"`

New coverage in `tests/test_scaffold_runner.py`:

- `test_scaffold_nestjs_adds_generate_openapi_script_entry`
- `test_scaffold_nestjs_adds_tsx_devdependency`
- `test_scaffold_nestjs_adds_swagger_dependency`
- `test_scaffold_idempotent_when_entries_already_present`
- `test_scaffold_when_no_package_json_exists`

Verification:

- `tests/test_scaffold_runner.py` -> `11 passed`
- `tests/test_v18_phase2_wave_engine.py -k "generate_openapi_contracts_uses_scaffolded_script_when_present"` -> `1 passed`

Session commit:

- `266e9ab` - `fix(scaffold): wire tsx devDep + @nestjs/swagger + npm script for Bug #8 completion`

## Bug #10 decision

Outcome: ratify the landed watchdog design.

The implementation already met the practical requirements for the re-run:

- configurable idle timeout
- hang report emission
- one retry on timeout
- tests for both timeout firing and healthy progress

The plan was updated in `docs/plans/2026-04-13-wave-d5-silent-hang-plan.md` with a new post-ratification implementation note describing the in-memory `_WaveWatchdogState` approach and its tradeoffs relative to the original heartbeat-file proposal.

Verification:

- `tests/test_v18_phase2_wave_engine.py -k "retries_sdk_timeout_once_and_writes_hang_report or does_not_timeout_with_periodic_progress"` -> `2 passed`

Session commit:

- `78907b8` - `docs(bug-10): ratify watchdog implementation; update plan with rationale`

## Test suite results

Targeted verification passed after each change:

- `tests/test_milestone_manager.py::TestParseDeps` -> `16 passed`
- `tests/test_scaffold_runner.py` -> `11 passed`
- `tests/test_v18_phase2_wave_engine.py -k "generate_openapi_contracts_uses_scaffolded_script_when_present"` -> `1 passed`
- `tests/test_v18_phase2_wave_engine.py -k "retries_sdk_timeout_once_and_writes_hang_report or does_not_timeout_with_periodic_progress"` -> `2 passed`

First full-suite run:

- `1 failed, 9953 passed, 35 skipped, 15 warnings in 616.98s`
- the only failure was `tests/test_v18_phase3_live_smoke.py::test_phase3_live_smoke_external_app`

Stabilization applied:

- added `_wait_for_server()` in `tests/test_v18_phase3_live_smoke.py`
- waits for the local `ThreadingHTTPServer` health endpoint before the test drives the live-smoke flow
- verified with 5 consecutive direct passes before the second full-suite run

Final full-suite run:

- `9954 passed, 35 skipped, 15 warnings in 555.09s`

The remaining 15 warnings are existing async/resource warnings in CLI wiring tests; they are not new regressions from this cleanup session.

## Re-run readiness

The smoke test re-run is now unblocked.

What changed materially:

- Bug #2 no longer drops `m-1`
- Bug #8 no longer leaves the Nest scaffold half-wired for scripted OpenAPI generation
- Bug #10 is explicitly ratified as the watchdog design to rely on during the re-run
- the rerun brief now includes Tier 2 stack-contract sentinels and updated Bug #10 expectations
- the test suite is green end-to-end

Residual concerns:

- Bug #5 still requires the clean-path workaround described in the rerun brief
- Bug #11 still needs manual Wave D review during the smoke test
- unrelated local worktree changes remain intentionally untouched

## Commits in this session

- `b57cb43` - accept hyphenated `m-1` shorthand in dependency parsing
- `266e9ab` - complete Nest scaffold `package.json` wiring for scripted OpenAPI generation
- `78907b8` - ratify the watchdog implementation and update the Bug #10 plan
- this commit - publish the cleanup report, refresh the smoke-test rerun brief, and include the live-smoke readiness wait that made the full suite stable

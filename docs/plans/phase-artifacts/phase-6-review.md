# Phase 6 — End-to-End Smoke Verification: Review Brief

This is the FINAL gate review of the dynamic orchestrator observer project. Phase 6 on its own is small (three deliverables), but its job is to confirm that every phase landed correctly, that the promotion gate is safe, and that nobody can accidentally ship `log_only: false` without a green calibration report. Review this phase as if the next action after approval is to push to master and run a live build.

## What Was Implemented

Phase 6 touches three files and only three:

1. `docs/AGENT_TEAMS_ACTIVATION.md` — activation checklist (8 ordered steps), minimum config snippet, communication-channels table, smoke protocol with JSONL log schema, calibration-report usage.
2. `tests/test_agent_teams_activation.py` — 8 test functions that verify the activation-doc claims are true in code:
   - `test_observer_config_has_log_only_default_true`
   - `test_observer_config_has_enabled_default_false`
   - `test_calibration_gate_exists`
   - `test_activation_step_3_is_enforced`
   - `test_communication_channels_exist`
   - `test_disabled_returns_cli_backend`
   - `test_enabled_without_env_var_returns_cli_backend`
   - `test_all_gates_open_returns_agent_teams_backend`
3. `tests/test_observer_integration.py` — 4 Level-B integration tests:
   - `test_claude_wave_peek_pipeline_wires_end_to_end`
   - `test_codex_notification_pipeline_emits_steer_in_log_only`
   - `test_calibration_gate_rejects_two_builds`
   - `test_config_round_trip_preserves_observer_and_phase_leads`

No runtime source code is modified. No new module is added. No smoke build is executed from tests.

## Full System Cross-Checks

This is the most important section of the review. Phase 6 is the first moment where the entire observer system is in-tree. Run every command below from the repo root on a clean checkout of the Phase 6 branch. Expected outputs noted inline.

### Correction audit (all 10 from the reviewer feedback)

```bash
cd C:/Projects/agent-team-v18-codex

# #1  _capture_file_fingerprints exists in wave_executor.py around line 2499
grep -n "_capture_file_fingerprints" src/agent_team_v15/wave_executor.py
# PASS criterion: at least one `def _capture_file_fingerprints` line plus >=1 call

# #2  AgentTeamConfig at ~line 1210 has observer field
grep -n "^class AgentTeamConfig\|observer: ObserverConfig" src/agent_team_v15/config.py
# PASS: both matches appear

# #3  codex_last_plan / codex_latest_diff live on _OrphanWatchdog in codex_appserver.py ONLY,
#     and are ABSENT from wave_executor.py
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py
# PASS: ZERO output
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/codex_appserver.py
# PASS: >=2 matches

# #4  _OrphanWatchdog declares those as INSTANCE attrs (self.x) not class attrs
grep -n "self\.codex_last_plan\|self\.codex_latest_diff" src/agent_team_v15/codex_appserver.py
# PASS: >=2 matches

# #5  execute_codex accepts existing_thread_id kwarg
grep -n "def execute_codex" src/agent_team_v15/codex_appserver.py
# Inspect the signature — PASS if `existing_thread_id` appears in the arglist
grep -n "existing_thread_id" src/agent_team_v15/codex_appserver.py
# PASS: >=1 match

# #6  _execute_once gets 3 new params (observer_config, peek_schedule, watchdog_state-adjacent)
grep -n "def _execute_once\|async def _execute_once" src/agent_team_v15/wave_executor.py
# Inspect the arglist manually — PASS if 3 Phase 5 params are present

# #7  peek_summary populated before the FINAL return of the wave body
grep -n "peek_summary" src/agent_team_v15/wave_executor.py
# PASS: field appears in WaveResult dataclass plus >=1 assignment BEFORE return

# #8  PhaseLeadsConfig preserves handoff_timeout_seconds
grep -n "handoff_timeout_seconds" src/agent_team_v15/config.py
# PASS: appears inside PhaseLeadsConfig dataclass body

# #9  No "or True" short-circuits in tests
grep -rn "or True" tests/
# PASS: ZERO output

# #10 Phase-leads wave-to-lead sanity test exists
grep -rn "test_wave_to_lead_references_valid_leads" tests/
# PASS: >=1 match
```

### New module presence

```bash
test -f src/agent_team_v15/observer_peek.py           && echo OK || echo MISSING
test -f src/agent_team_v15/replay_harness.py          && echo OK || echo MISSING
test -f src/agent_team_v15/codex_lead_bridge.py       && echo OK || echo MISSING
test -f src/agent_team_v15/codex_observer_checks.py   && echo OK || echo MISSING
test -f docs/AGENT_TEAMS_ACTIVATION.md                && echo OK || echo MISSING
test -f tests/test_agent_teams_activation.py          && echo OK || echo MISSING
test -f tests/test_observer_integration.py            && echo OK || echo MISSING
```
Every echo must be OK. Zero output from the import checks (no BLOCKED messages) is required. If any module is missing, REJECT immediately.

### Activation doc completeness

```bash
grep -c "Run 3+ builds" docs/AGENT_TEAMS_ACTIVATION.md                # >=1
grep -c "generate_calibration_report" docs/AGENT_TEAMS_ACTIVATION.md  # >=1
grep -c "log_only: false" docs/AGENT_TEAMS_ACTIVATION.md              # >=1
grep -c "agent_teams.enabled" docs/AGENT_TEAMS_ACTIVATION.md          # >=1
grep -c "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" docs/AGENT_TEAMS_ACTIVATION.md  # >=1
grep -c "observer_log.jsonl" docs/AGENT_TEAMS_ACTIVATION.md           # >=1
grep -c "turn/steer" docs/AGENT_TEAMS_ACTIVATION.md                   # >=1 (comms table)
grep -c "CODEX_WAVE_COMPLETE" docs/AGENT_TEAMS_ACTIVATION.md          # >=1 (comms table)
grep -c "STEER_REQUEST" docs/AGENT_TEAMS_ACTIVATION.md                # >=1 (comms table)
```

Any zero indicates the doc is missing a required section.

### Wiring checks (prove every phase reaches across module boundaries)

```bash
# Observer config reachable from wave_executor
grep -n "ObserverConfig\|observer_config\|observer_cfg\|_obs_cfg\b\|_obs\b" src/agent_team_v15/wave_executor.py
# PASS: >=1 match

# MESSAGE_TYPES widened to carry cross-protocol traffic
grep -n "CODEX_WAVE_COMPLETE\|STEER_REQUEST" src/agent_team_v15/agent_teams_backend.py
# PASS: both strings appear

# turn_steer is exported / importable from codex_appserver
grep -n "def turn_steer\|async def turn_steer" src/agent_team_v15/codex_appserver.py
# PASS: >=1 match

# Phase-lead bridge uses route_message
grep -n "route_message" src/agent_team_v15/codex_lead_bridge.py
# PASS: >=1 match
```

## Code Review Checklist

Reviewer runs each item and answers OK / DEFECT with evidence.

### Activation doc (`docs/AGENT_TEAMS_ACTIVATION.md`)
- [ ] All 8 activation steps present, in the order mandated.
- [ ] Step 2 explicitly says `3+ builds`.
- [ ] Step 3 says `safe_to_promote: true` AND `FP rate < 10%`.
- [ ] Step 4 comes AFTER step 3 (i.e., no wording that suggests flipping log_only without the report).
- [ ] Step 6 mentions `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (spell check).
- [ ] Communication-channel table has 7 rows, matches the Phase 6 spec exactly.
- [ ] JSONL example in "Running Calibration Builds" section matches the keys actually written by `observer_peek._emit_log_entry` (read source to confirm).
- [ ] "Calibration Report" section does not instruct the operator to hand-edit the JSONL or bypass the gate.
- [ ] No promises of features that don't exist (e.g., don't claim `log_only` is set per-wave if it's global).

### Gate-test file (`tests/test_agent_teams_activation.py`)
- [ ] Uses `monkeypatch.delenv` — not `os.environ.pop` — to remove env vars in the `test_enabled_without_env_var_returns_cli_backend` test (so the removal is reverted after the test).
- [ ] `test_activation_step_3_is_enforced` creates the JSONL under `tmp_path/.agent-team/` (matches `replay_harness.generate_calibration_report` expectation).
- [ ] `test_all_gates_open_returns_agent_teams_backend` handles the case where `claude` CLI isn't installed (accepts `RuntimeError` with "claude" in message).
- [ ] No `or True`, no `pytest.skip` without condition, no `assert True`.
- [ ] No network calls, no `AsyncAnthropic` import executed.

### Integration-test file (`tests/test_observer_integration.py`)
- [ ] Each test declares `tmp_path` / `monkeypatch` only when used.
- [ ] Mocks are applied at the `module.attr` level via `monkeypatch.setattr` — not by hand-patching globals.
- [ ] `test_claude_wave_peek_pipeline_wires_end_to_end` — asserts both that the peek fires AND that `did_interrupt` is false when `log_only=True`. It MUST assert `did_interrupt is False`.
- [ ] `test_codex_notification_pipeline_emits_steer_in_log_only` — asserts `steer_calls == []` (no actual turn_steer call) when `log_only=True`.
- [ ] `test_calibration_gate_rejects_two_builds` — uses 2 distinct dates (the existing `generate_calibration_report` counts distinct `timestamp[:10]` values). Confirm asserts `safe_to_promote is False`.
- [ ] `test_config_round_trip_preserves_observer_and_phase_leads` — checks BOTH `cfg.observer` fields AND `cfg.phase_leads.handoff_timeout_seconds` (correction #8 coverage).
- [ ] No test awaits a real network call; no test spawns a subprocess.
- [ ] No test imports `anthropic` directly (the import belongs inside `observer_peek.py`, not tests).

### Pre-existing test regressions
- [ ] If `python -m pytest tests/ -v --tb=short -x` fails on a test unrelated to Phase 0–6, the Phase 6 handoff documents the failing test's name, the first error line, and a note that it pre-existed. Reviewer confirms this is truly pre-existing by running `git stash && git checkout master -- tests/<file>` and comparing. DO NOT accept vague "it was broken before" claims.

## Adversarial Checks

These are the ways Phase 6 could ship broken. Review agent MUST probe each.

1. **Gate smuggling.** Grep the activation doc for the word "optional", "skip", or "if you are confident". If any appear near step 3, REJECT — the calibration report must be mandatory.
2. **Silent log_only default flip.** Inspect `ObserverConfig.log_only` default. If it is not `True` at the dataclass definition, REJECT — correction #3's safety property is violated.
3. **Missing did_interrupt assertion.** In `test_claude_wave_peek_pipeline_wires_end_to_end`, if `did_interrupt` is not asserted False, the test would pass even if log_only was ignored and a real interrupt fired. REJECT.
4. **Fake integration test.** If all 4 integration tests only import and assert module-level attributes (no actual cross-module call), they are disguised unit tests. Reviewer reads each test body and confirms at least one real function call to a Phase 0–5 module happens per test.
5. **JSONL schema drift.** Read `observer_peek.py` and find the log emit site. Compare its fields against the JSONL example in `AGENT_TEAMS_ACTIVATION.md`. If they disagree (missing key, renamed key), REJECT the doc.
6. **Env-var leak.** `test_enabled_without_env_var_returns_cli_backend` must use `monkeypatch.delenv`. If it uses `os.environ.pop`, the env var removal persists across tests and pollutes the suite. REJECT.
7. **`generate_calibration_report` signature mismatch.** The plan has two versions in the repo (sync `generate_calibration_report(cwd: str)` returning `CalibrationReport`, and an async variant via `ReplayRunner`). Confirm the test calls the version that actually exists. Read `src/agent_team_v15/replay_harness.py` first. If the signature does not match what the test calls, REJECT.
8. **`test_all_gates_open_returns_agent_teams_backend` masking.** The test accepts either success OR `RuntimeError` with "claude" in the message. Confirm the `RuntimeError` path is genuinely the "claude CLI not installed" case by reading `create_execution_backend`. If any other RuntimeError could pass the check (e.g., unrelated config error), REJECT and tighten the assertion.
9. **Activation doc drift vs code.** The doc claims `fallback_to_cli: true` is a safe default. Confirm in `AgentTeamsConfig` that `fallback_to_cli` defaults to True. If not, REJECT.
10. **Hidden `or True` in new tests.** `grep -rn "or True" tests/` must return empty. Run it. If any match appears even in the Phase 6 tests themselves, REJECT.
11. **`test_wave_to_lead_references_valid_leads` actually tests something.** Read the test body. If it is `assert True` or `assert WAVE_TO_LEAD` (truthy-check of a non-empty dict), REJECT. It must iterate over `WAVE_TO_LEAD.values()` and cross-check each lead name against `PHASE_LEAD_NAMES`.
12. **No new top-level `or`-chained assertion in activation tests.** `assert condition_a or condition_b` where either can spuriously pass is equivalent to `or True`. Grep for `assert.*\bor\b` in the two new test files and inspect every hit.
13. **peek_summary populated path.** Read the `_execute_once` / wave body in `wave_executor.py`. Confirm `peek_summary` is assigned BEFORE the final `return WaveResult(...)` on BOTH the success path and at least one failure path. If only the success path populates it, REJECT (correction #7 only half-landed).
14. **PhaseLeadsConfig preservation.** `PhaseLeadsConfig` must still declare `handoff_timeout_seconds` (correction #8). Phase 1 renamed other fields; confirm nothing collateral was dropped by diffing `PhaseLeadsConfig` against its pre-Phase-1 form.
15. **Orphan watchdog location.** Correction #3 requires `codex_last_plan` / `codex_latest_diff` ON `_OrphanWatchdog` and NOT on `_WaveWatchdogState`. The greps above cover this; the reviewer must also open both classes and confirm no shadow attribute (even unused).
16. **Missing Phase 5 parameter.** If `_execute_once` signature does not include the three new params, Phase 5 is broken and Phase 6 tests likely can't exercise the peek path. Read the signature. Confirm all three.

## Test Run Commands

```bash
cd C:/Projects/agent-team-v18-codex

# 1. Phase 6 targeted tests
python -m pytest tests/test_agent_teams_activation.py -v --tb=short
python -m pytest tests/test_observer_integration.py -v --tb=short

# 2. Full suite — strict
python -m pytest tests/ -v --tb=short -x

# 3. Activation doc keyword count (Phase 6 gate)
grep -c "Run 3+ builds\|generate_calibration_report\|log_only: false\|agent_teams.enabled\|CLAUDE_CODE_EXPERIMENTAL\|observer_log.jsonl" \
  docs/AGENT_TEAMS_ACTIVATION.md
# expect >= 6

# 4. Cross-phase correction audit (all 10)
grep -n "_capture_file_fingerprints" src/agent_team_v15/wave_executor.py
grep -n "observer: ObserverConfig" src/agent_team_v15/config.py
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py     # expect empty
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/codex_appserver.py   # expect 2+
grep -n "self\.codex_last_plan" src/agent_team_v15/codex_appserver.py
grep -n "existing_thread_id" src/agent_team_v15/codex_appserver.py
grep -n "def _execute_once\|async def _execute_once" src/agent_team_v15/wave_executor.py
grep -n "peek_summary" src/agent_team_v15/wave_executor.py
grep -n "handoff_timeout_seconds" src/agent_team_v15/config.py
grep -rn "or True" tests/                                                             # expect empty
grep -rn "test_wave_to_lead_references_valid_leads" tests/

# 5. No lingering TODO/FIXME/XXX in new Phase 6 files
grep -nE "TODO|FIXME|XXX" docs/AGENT_TEAMS_ACTIVATION.md \
  tests/test_agent_teams_activation.py \
  tests/test_observer_integration.py
# expect empty
```

## Final Acceptance Criteria

Phase 6 (and the whole observer project) is approved for merge when ALL of the following are true:

1. All four test-run commands above exit 0.
2. Every correction audit grep produces the expected result (non-empty for positive assertions, empty for the two negative assertions on `codex_last_plan` in `wave_executor.py` and `or True` in `tests/`).
3. All 16 adversarial checks pass — reviewer explicitly marks each as OK with a one-line evidence note (file:line).
4. `docs/AGENT_TEAMS_ACTIVATION.md` includes all 8 activation steps AND the 7-row communication-channels table verbatim.
5. All four integration tests exercise a real cross-module call (not just attribute assertions).
6. `ObserverConfig.log_only` defaults to `True` and `ObserverConfig.enabled` defaults to `False` — verified by the two explicit tests.
7. `generate_calibration_report` on 2 distinct-day log entries returns `safe_to_promote=False` — verified by `test_activation_step_3_is_enforced` and `test_calibration_gate_rejects_two_builds`.
8. No pre-existing test regressed. If a pre-existing failure is claimed, the Phase 6 handoff names the test, links the prior failing CI run, and reviewer independently confirms.
9. Git log shows a single Phase 6 commit (or two at most — docs + tests). No drive-by source changes under `src/agent_team_v15/` in the Phase 6 commits.
10. No file outside `docs/AGENT_TEAMS_ACTIVATION.md` / `tests/test_agent_teams_activation.py` / `tests/test_observer_integration.py` is modified by Phase 6.

If any acceptance criterion is NOT met, Phase 6 is REJECTED. Do not negotiate — the project cannot merge until the underlying issue is fixed, because Phase 6 is the last safety gate before live deployment. Err on the side of sending it back.

### Relevant paths

- `C:/Projects/agent-team-v18-codex/docs/AGENT_TEAMS_ACTIVATION.md`
- `C:/Projects/agent-team-v18-codex/tests/test_agent_teams_activation.py`
- `C:/Projects/agent-team-v18-codex/tests/test_observer_integration.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/observer_peek.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/replay_harness.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_lead_bridge.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_observer_checks.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/agent_teams_backend.py`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/config.py`
- `C:/Projects/agent-team-v18-codex/docs/plans/2026-04-20-dynamic-orchestrator-observer.md`

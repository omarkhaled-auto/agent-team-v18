# Phase 1 — Phase Lead System: Review Brief

## What Was Implemented

Phase 1 rewires the `AgentTeamsBackend` phase-lead taxonomy to match the wave roster and adds a new cross-protocol bridge so Codex waves can talk to Claude leads.

- Renamed `PHASE_LEAD_NAMES` from six generic names (`planning-lead`, `architecture-lead`, `coding-lead`, `review-lead`, `testing-lead`, `audit-lead`) to the four wave-aligned names (`wave-a-lead`, `wave-d5-lead`, `wave-t-lead`, `wave-e-lead`).
- Renamed fields in `PhaseLeadsConfig` to match: `planning_lead` → `wave_a_lead`, `architecture_lead` → (dropped; folded into `wave_a_lead`), `coding_lead` → (dropped), `review_lead` → (dropped), `testing_lead` → `wave_t_lead`, `audit_lead` → (dropped; Wave E covers verification/audit), plus `wave_d5_lead` and `wave_e_lead` as new fields. Preserved `handoff_timeout_seconds` and `allow_parallel_phases` (correction #8).
- Added `CODEX_WAVE_COMPLETE` and `STEER_REQUEST` to `MESSAGE_TYPES`.
- Migrated callers in `agents.py` and `cli.py` and updated tests in `test_phase_lead_integration.py`, `test_isolated_to_team_pipeline.py`, `test_isolated_to_team_simulation.py`, `test_agent_teams_backend.py`.
- New module `src/agent_team_v15/codex_lead_bridge.py` with `WAVE_TO_LEAD`, `route_codex_wave_complete`, `read_pending_steer_requests` — both public functions fail-open.
- New tests: `test_phase_lead_roster.py` (4 tests including correction #10 cross-validation), `test_phase_lead_messaging.py` (3 tests), `test_codex_lead_bridge.py` (8 tests including the cross-validation that every WAVE_TO_LEAD value exists in PHASE_LEAD_NAMES).

## Critical Pre-Checks

Run these **before** reading the diff. They catch the most common rushed-agent failure modes.

1. **Did the agent preserve `handoff_timeout_seconds` and `allow_parallel_phases`?** (Correction #8 is the single most commonly skipped item.)
   ```bash
   grep -n "handoff_timeout_seconds\|allow_parallel_phases" src/agent_team_v15/config.py
   ```
   Must list two lines inside the `PhaseLeadsConfig` dataclass. If either is missing, Phase 1 is incomplete — reject.

2. **Are legacy names really gone from `PHASE_LEAD_NAMES`?** A sloppy implementer might leave them behind "for compatibility".
   ```bash
   python -c "
   import pathlib, re
   src = pathlib.Path('src/agent_team_v15/agent_teams_backend.py').read_text()
   m = re.search(r'PHASE_LEAD_NAMES[^]]+\]', src, re.DOTALL)
   block = m.group(0) if m else ''
   for stale in ('planning-lead','architecture-lead','coding-lead','review-lead','testing-lead','audit-lead'):
       assert stale not in block, f'Legacy name {stale!r} still in PHASE_LEAD_NAMES'
   print('ok')
   "
   ```
   Must print `ok`. Finding a legacy name means the rename was aborted midway — reject.

3. **Did the agent migrate the known external callers?** There are six known sites outside `agent_teams_backend.py` and `config.py` that reference the old field names. All must be updated.
   ```bash
   grep -rn "phase_leads\.\(planning\|architecture\|coding\|review\|testing\|audit\)_lead" src/ tests/
   ```
   Expected: **zero matches**. Any hit is a regression — the next run of that caller will raise `AttributeError`.

4. **Did the bridge module get created with both public functions?**
   ```bash
   python -c "from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD, route_codex_wave_complete, read_pending_steer_requests; print('ok')"
   ```

5. **Are new message types present without accidentally dropping legacy ones?**
   ```bash
   python -c "
   from agent_team_v15.agent_teams_backend import AgentTeamsBackend as B
   legacy = {'REQUIREMENTS_READY','ARCHITECTURE_READY','WAVE_COMPLETE','REVIEW_RESULTS','DEBUG_FIX_COMPLETE','WIRING_ESCALATION','CONVERGENCE_COMPLETE','TESTING_COMPLETE','ESCALATION_REQUEST','SYSTEM_STATE','RESUME'}
   assert legacy.issubset(B.MESSAGE_TYPES), legacy - B.MESSAGE_TYPES
   assert 'CODEX_WAVE_COMPLETE' in B.MESSAGE_TYPES and 'STEER_REQUEST' in B.MESSAGE_TYPES
   print('ok')
   "
   ```

## Code Review Checklist

### Correctness

- [ ] `PHASE_LEAD_NAMES` is exactly `["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]` — not a subset, not a superset.
- [ ] `PhaseLeadsConfig` has all six expected fields: `wave_a_lead`, `wave_d5_lead`, `wave_t_lead`, `wave_e_lead`, `handoff_timeout_seconds`, `allow_parallel_phases`. No stale `planning_lead`/`architecture_lead`/`coding_lead`/`review_lead`/`testing_lead`/`audit_lead`.
- [ ] `_get_phase_lead_config()` maps every entry in `PHASE_LEAD_NAMES` — no key missing, no typos, and an unknown name returns `None` (matching today's `.get(lead_name)` behavior; do not silently return a blank `PhaseLeadConfig()` instead).
- [ ] `MESSAGE_TYPES` still contains all 11 legacy entries *and* the two new ones. Total set size is 13.
- [ ] `WAVE_TO_LEAD` is exactly `{"A5": "wave-a-lead", "B": "wave-a-lead", "D": "wave-d5-lead", "T5": "wave-t-lead"}`. Wave C and Scaffold are **absent** (they are static Python with no agent). Wave A, D5, T, E are **absent** (they are Claude-native, not Codex).
- [ ] `route_codex_wave_complete()` writes a file whose name starts with `msg_` and uses the same `msg_{timestamp}_{from}_to_{recipient}.md` pattern used by `AgentTeamsBackend.route_message` (line ~909). Filename drift will break any code path that globs the context dir.
- [ ] `route_codex_wave_complete()` writes a `Type: CODEX_WAVE_COMPLETE` header, not `Type: WAVE_COMPLETE` (the Claude-only type already exists).

### Architecture

- [ ] Both bridge functions are wrapped in `try/except OSError`. They must **never** raise — the orchestrator depends on fail-open semantics.
- [ ] `read_pending_steer_requests()` returns `[]` (not `None`, not raises) when `context_dir` does not exist.
- [ ] `route_codex_wave_complete()` is a no-op (silent log, no raise) when `wave_letter` is not in `WAVE_TO_LEAD`. Look for an explicit `if lead is None: return` guard.
- [ ] `codex_lead_bridge.py` imports **only** stdlib (`logging`, `time`, `pathlib`). It must not import from `agent_teams_backend` (would cause a circular dependency once the backend later imports the bridge). The cross-validation test imports both separately — that is deliberate and correct.
- [ ] `agents.py` lines 5426–5431 no longer reference the old six field names. Read the replacement dict and confirm the prompt constants (`ARCHITECTURE_LEAD_PROMPT`, `CODING_LEAD_PROMPT`, `TESTING_LEAD_PROMPT`, `REVIEW_LEAD_PROMPT`, and the dynamic `_arch_prompt` if still in scope) still compile.
- [ ] `cli.py:2858` no longer references `audit_lead`. Confirm it was remapped to `wave_e_lead` (not `wave_t_lead`).

### Test Quality

- [ ] `test_wave_to_lead_references_valid_leads` actually iterates `WAVE_TO_LEAD` and checks membership in `PHASE_LEAD_NAMES`. **Adversarial check:** a lazy agent might write `assert WAVE_TO_LEAD`, which passes trivially. Open the test file and verify it reads something equivalent to:
  ```python
  for wave, lead in WAVE_TO_LEAD.items():
      assert lead in AgentTeamsBackend.PHASE_LEAD_NAMES
  ```
  Reject if the body lacks a `for` loop or does not touch `PHASE_LEAD_NAMES`.
- [ ] None of the new tests contain `or True`, `assert True`, `pytest.skip(...)`, `if False`, or `@pytest.mark.skip`. Run:
  ```bash
  grep -nE "or True|assert True|pytest\.skip|@pytest\.mark\.skip|if False" tests/test_phase_lead_roster.py tests/test_phase_lead_messaging.py tests/test_codex_lead_bridge.py
  ```
  Expected: no output. (Correction #9 lineage — make sure the lesson was absorbed.)
- [ ] The bridge tests cover both the success path and the fail-open paths (unknown wave, missing directory, unreadable file).
- [ ] `test_route_codex_wave_complete_writes_file` asserts a specific filename shape (glob `msg_*_codex-wave-b_to_wave-a-lead.md`), not just "some file exists". Loose assertions hide drift.

### Integration Safety

- [ ] Running `python -m pytest tests/ -k "phase_lead or codex_lead_bridge or agent_teams_backend or isolated_to_team"` passes. Any legacy test that now fails is either a stale assertion (which must be migrated) or a genuine regression (which must be investigated — **do not delete the test** to make CI green).
- [ ] No `AttributeError: 'PhaseLeadsConfig' object has no attribute 'planning_lead'` anywhere in the test output. If one appears, a migration site was missed.
- [ ] `enterprise_mode.enabled=True` still forces `phase_leads.enabled=True` (see `config.py:2480`) — the rename must not break that coercion.
- [ ] Verify Phase 0 artefacts still pass: `python -m pytest tests/test_codex_appserver_steer.py tests/test_codex_notifications.py -v` (regression gate from Phase 0 — Phase 1 should not touch these).

## Test Run Commands

```bash
cd C:/Projects/agent-team-v18-codex

# Phase 1 new tests
python -m pytest tests/test_phase_lead_roster.py tests/test_phase_lead_messaging.py tests/test_codex_lead_bridge.py -v

# Migrated legacy tests
python -m pytest tests/test_phase_lead_integration.py tests/test_isolated_to_team_pipeline.py tests/test_isolated_to_team_simulation.py tests/test_agent_teams_backend.py -v

# Phase 0 regression gate
python -m pytest tests/test_codex_appserver_steer.py tests/test_codex_notifications.py -v

# Full sanity sweep across the package
python -m pytest tests/ -x --ignore=tests/test_v18_smoke -q
```

Every invocation must exit 0. A single failure blocks the phase.

## Acceptance Criteria

Phase 1 is accepted when **all** of the following hold:

1. All six Phase Gate commands in `phase-1-impl.md` exit 0.
2. All Critical Pre-Checks above pass (explicitly document the output of each on the PR/commit).
3. No legacy phase-lead names appear anywhere in `src/agent_team_v15/`:
   ```bash
   grep -rn "planning-lead\|architecture-lead\|coding-lead\|review-lead\|testing-lead\|audit-lead" src/agent_team_v15/
   ```
   Expected: zero matches (docstrings and `agents.py` lines 652–661 / 1554–1601 / 5426–5431 may have been removed or rewritten; if any references remain they must be in a comment that documents the migration, not in live code or public prompts).
4. No legacy `PhaseLeadsConfig` field names appear anywhere in `src/` or `tests/`:
   ```bash
   grep -rn "phase_leads\.\(planning\|architecture\|coding\|review\|testing\|audit\)_lead" src/ tests/
   ```
   Expected: zero matches.
5. `codex_lead_bridge.py` exists, imports cleanly, and every public function has `try/except OSError` wrapping its I/O.
6. `tests/test_codex_lead_bridge.py::test_wave_to_lead_references_valid_leads` is implemented as an *actual* cross-validation loop (not a trivially-passing stub).
7. `PhaseLeadsConfig().handoff_timeout_seconds == 300` and `PhaseLeadsConfig().allow_parallel_phases is True` — correction #8 retained verbatim.
8. `MESSAGE_TYPES` has exactly 13 entries: the 11 legacy ones plus `CODEX_WAVE_COMPLETE` and `STEER_REQUEST`.
9. `WAVE_TO_LEAD` has exactly 4 keys — `A5`, `B`, `D`, `T5` — and every value is in `PHASE_LEAD_NAMES`.
10. Commit history contains three distinct commits (one per task) with conventional messages referencing `Phase 1 Task 1.1`, `1.2`, `1.3`.

Reject and send back if any item fails. Do not accept "99% complete" — a missed migration site in `agents.py` or `cli.py` will break the orchestrator at the next Claude wave spawn.

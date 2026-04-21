# Phase 1 — Review Report

**Reviewer:** Claude (Opus 4.7)
**Reviewed commit:** `cf7caa01e4ad6d19689f657d7c42ba0883c68377`
**Reviewed worktree:** `C:\Projects\agent-team-v18-codex-master-merge` (branch `master`, 1 commit ahead of `origin/master`)
**Review date:** 2026-04-21
**Verdict:** **REJECT — send back for remediation.**

The implementation of the four Phase 1 product requirements (roster rename, message-type additions, config field rename, `codex_lead_bridge` module) is **correct and of good quality**. Every narrow Phase Gate command in `phase-1-impl.md` exits 0. But two acceptance criteria in `phase-1-review.md` are violated, and a significant regression surface exists in the wider test suite that the implementer chose not to run before claiming success.

---

## 1. Critical Pre-Checks — 5/5 PASS

| # | Pre-check | Result |
|---|-----------|--------|
| 1 | `handoff_timeout_seconds` + `allow_parallel_phases` preserved in `PhaseLeadsConfig` | **PASS** — `config.py:576-577` |
| 2 | Legacy names absent from `PHASE_LEAD_NAMES` | **PASS** — list is exactly the 4 wave names (`agent_teams_backend.py:289-294`) |
| 3 | `grep -rn "phase_leads\.(planning\|architecture\|coding\|review\|testing\|audit)_lead" src/ tests/` | **PASS** — zero matches |
| 4 | `codex_lead_bridge` imports cleanly with both public functions + `WAVE_TO_LEAD` | **PASS** |
| 5 | `MESSAGE_TYPES` preserves all 11 legacy entries + adds `CODEX_WAVE_COMPLETE`, `STEER_REQUEST` (size 13) | **PASS** |

---

## 2. Correctness Checklist — PASS

- `PHASE_LEAD_NAMES == ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]` exactly (`agent_teams_backend.py:289-294`).
- `PhaseLeadsConfig` fields are exactly the six expected; no stale legacy fields (`config.py:563-577`).
- `_get_phase_lead_config()` uses `.get(lead_name)` so unknown names return `None` (`agent_teams_backend.py:695-702`). Maps every entry in `PHASE_LEAD_NAMES`.
- `MESSAGE_TYPES` size is 13 (11 legacy + 2 new).
- `WAVE_TO_LEAD` is exactly `{"A5": "wave-a-lead", "B": "wave-a-lead", "D": "wave-d5-lead", "T5": "wave-t-lead"}` — Wave C/Scaffold/A/D5/T/E correctly absent.
- `route_codex_wave_complete` filename follows `msg_{ts}_{from}_to_{recipient}.md` pattern matching `AgentTeamsBackend.route_message` (`codex_lead_bridge.py:67` vs `agent_teams_backend.py:907`).
- Header is `Type: CODEX_WAVE_COMPLETE`, not `Type: WAVE_COMPLETE` (`codex_lead_bridge.py:61`).

---

## 3. Architecture Checklist — PASS

- Both bridge functions wrapped in `try/except OSError`; never raise (`codex_lead_bridge.py:47-81, 96-122`).
- `read_pending_steer_requests()` returns `[]` when `context_dir` does not exist (`codex_lead_bridge.py:100-101`).
- `route_codex_wave_complete()` is no-op (info log, no raise) for unknown wave letters (`codex_lead_bridge.py:48-54`).
- `codex_lead_bridge.py` imports only stdlib (`logging`, `time`, `pathlib`). No import from `agent_teams_backend` — no circular dependency risk.
- `agents.py:5425-5430` replaced the six legacy field references with the four wave-aligned ones. `ARCHITECTURE_LEAD_PROMPT`, `CODING_LEAD_PROMPT`, `TESTING_LEAD_PROMPT`, `REVIEW_LEAD_PROMPT`, `PLANNING_LEAD_PROMPT`, and `ENTERPRISE_ARCHITECTURE_STEPS` still exist and compile.
- `cli.py:2894-2899` correctly remapped `audit_lead` → `wave_e_lead` (not `wave_t_lead`).
- `enterprise_mode.enabled=True` → `phase_leads.enabled=True` coercion still in place at `config.py:2514-2518`.
- `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` fully migrated: 0 legacy names, 48 wave-* references.

---

## 4. Test Quality Checklist — PASS

- `test_wave_to_lead_references_valid_leads` is a real `for`-loop cross-validation touching `AgentTeamsBackend.PHASE_LEAD_NAMES` (`tests/test_codex_lead_bridge.py:19-28`).
- `grep -nE "or True|assert True|pytest\.skip|@pytest\.mark\.skip|if False"` over the three new test files: **no output**.
- Fail-open paths covered: unknown wave, missing directory (both sides), success path, empty-dir read. (Minor note: "unreadable file" is not explicitly fault-injected — the code defends via `try/except OSError` at line 105-111, but no test proves it. Non-blocking.)
- `test_route_codex_wave_complete_writes_file` asserts the specific glob `msg_*_codex-wave-b_to_wave-a-lead.md` (line 40).

---

## 5. Test Run Results

| Suite | Command | Result |
|---|---|---|
| Phase 1 new tests | `pytest tests/test_phase_lead_roster.py tests/test_phase_lead_messaging.py tests/test_codex_lead_bridge.py` | **15/15 PASS** |
| Migrated legacy tests | `pytest tests/test_phase_lead_integration.py tests/test_isolated_to_team_pipeline.py tests/test_isolated_to_team_simulation.py tests/test_agent_teams_backend.py` | **246/246 PASS** |
| Phase 0 regression gate | `pytest tests/test_codex_appserver_steer.py tests/test_codex_notifications.py` | **9/9 PASS** |
| Full sanity sweep | `pytest tests/ -x --ignore=tests/test_v18_smoke -q` | **FAIL** (see §6) |

All six narrow **Phase Gate** commands in `phase-1-impl.md` exit 0 when run individually.

---

## 6. Full-Sweep Regressions — 19 new failures introduced by Phase 1

`phase-1-review.md` §"Test Run Commands" explicitly states: *"Every invocation must exit 0. A single failure blocks the phase."* The fourth command — the full sanity sweep — fails.

I compared the failure set against the pre-Phase 1 baseline (commit `7425b33`, the parent of `cf7caa0`) by checking out that tree's `src/` and `tests/` and rerunning. **8 failures / errors** pre-existed on master and are not Phase 1's responsibility (`test_h1a_wiring.py` ×2, `test_scaffold_verifier_post_scaffold.py`, `test_scaffold_wave_dispatch.py` ×2, `test_walker_sweep_complete.py::test_no_unsafe_rglob_in_agent_team_v15`, `test_walker_sweep_complete.py::test_allow_list_entries_have_safety_comment_or_docstring`, `test_carry_forward_c_cf.py` [missing fixture dir], `test_n08_audit_fix_observability.py` [error]).

**19 failures are new and caused by Phase 1:**

### 6.1 Stale legacy-roster assertions (18 failures, 9 files) — MIGRATION REQUIRED

These tests hard-code the old roster names (`planning-lead`, `architecture-lead`, `coding-lead`, `review-lead`, `testing-lead`, `audit-lead`). The review brief is explicit: *"Any legacy test that now fails is either a stale assertion (which must be migrated) or a genuine regression (which must be investigated — **do not delete the test** to make CI green)."* These were not migrated.

| Test file | Failure count | Nature of stale refs |
|---|---:|---|
| `tests/test_department_integration.py` | 4 | Iterates the 6 old names (lines 148-149, 255-256, 314-315, 557-561) |
| `tests/test_department_model.py` | 2 | Asserts `"coding-lead" in defs` etc. (lines 619-662) |
| `tests/test_enterprise_agents.py` | 1 | `assert "coding-lead"/"review-lead"/"architecture-lead" in defs` (63-65) |
| `tests/test_enterprise_final_simulation.py` | 4 | Iterates 6 old names, `defs["architecture-lead"]` KeyError (141-188, 417-419) |
| `tests/test_new10_step2_enterprise_mode.py` | 1 | Asserts old names appear in orchestrator prompt section (50-78) |
| `tests/test_orchestrator_prompt.py` | 1 | `"review-lead"/"testing-lead"/"audit-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT` (120-122) |
| `tests/test_prompt_integrity.py` | 4 | `"audit-lead" in after_sec15`, slim-prompt checks (452, 493 etc.) |
| `tests/test_team_simulation.py` | 1 | Iterates 5 old names (200) |

Plus `tests/verify_enterprise_live.py:106` (`defs["architecture-lead"]["prompt"]`) — not a pytest target but same bug.

**The source-of-truth migration is fine** — `TEAM_ORCHESTRATOR_SYSTEM_PROMPT` now contains 0 legacy names and 48 wave-* references, and `build_agent_definitions()` returns the wave-aligned keys. So these tests are not reporting genuine bugs; they are asserting on frozen identifiers that no longer exist. But they must be migrated (to the wave-aligned roster) before the sweep exits 0.

### 6.2 Genuine walker-sweep regression (1 failure) — SMALL FIX

`tests/test_walker_sweep_complete.py::test_no_unsafe_glob_doublestar_in_agent_team_v15` fails because the allow-list entry at line 111 declares the anti-pattern comment sits at `agents.py:7702`, but Phase 1's edits to `agents.py` shifted the comment to `agents.py:7696`. This test did pass on master pre-Phase 1.

Fix: update `tests/test_walker_sweep_complete.py:111` from `7702` to `7696`. Do **not** weaken the assertion or add an exclusion — just sync the line number.

---

## 7. Acceptance Criteria — 8/10 PASS

| # | Criterion | Result |
|---:|---|---|
| 1 | All six Phase Gate commands in `phase-1-impl.md` exit 0 | **PASS** |
| 2 | All Critical Pre-Checks pass | **PASS** |
| 3 | No legacy phase-lead names in `src/agent_team_v15/` | **PASS** (0 matches) |
| 4 | No legacy `phase_leads.*_lead` references in `src/` or `tests/` | **PASS** (0 matches) |
| 5 | `codex_lead_bridge.py` exists, imports cleanly, `try/except OSError` wraps all I/O | **PASS** |
| 6 | `test_wave_to_lead_references_valid_leads` is a real cross-validation loop | **PASS** |
| 7 | `PhaseLeadsConfig().handoff_timeout_seconds == 300 and .allow_parallel_phases is True` | **PASS** |
| 8 | `MESSAGE_TYPES` has exactly 13 entries (11 legacy + 2 new) | **PASS** |
| 9 | `WAVE_TO_LEAD` has exactly 4 keys, every value in `PHASE_LEAD_NAMES` | **PASS** |
| 10 | **Three distinct commits (one per Task 1.1 / 1.2 / 1.3)** with conventional messages | **FAIL** |

### On criterion #10

`phase-1-impl.md` explicitly directs the implementer to commit after each task:
- line 265: `Commit with message: "Phase 1 Task 1.1: rename phase leads to wave-aligned names"`
- line 581: `Commit with message: "Phase 1 Task 1.3: add codex_lead_bridge module for Codex→Claude messaging"`
- (Task 1.2 similarly)

Actual history shows **one commit** — `cf7caa0 "Phase 1: implement wave-aligned phase leads"` — containing all three tasks bundled. This is a direct violation of acceptance criterion #10. Splitting is important because (a) it preserves per-task bisect granularity, and (b) the reviewer should be able to verify each task in isolation.

### Implicit failure: full sweep

The full sanity sweep is listed under §"Test Run Commands" with the directive *"Every invocation must exit 0. A single failure blocks the phase."* Although not numbered in the 10 acceptance criteria, this is the gating directive in the preceding section. The 19 new failures (§6) block it.

---

## 8. Required Remediation (for re-review)

1. **Migrate 9 stale legacy-roster test files** (§6.1). Map old → new per `ARCHITECTURE_LEAD_PROMPT` → wave-d5-lead (owns architecture per `agents.py:5427`), `REVIEW_LEAD_PROMPT` → wave-e-lead, `TESTING_LEAD_PROMPT` → wave-t-lead, `PLANNING_LEAD_PROMPT` → wave-a-lead, `audit-lead` → wave-e-lead, `coding-lead` → (no 1:1 — Wave B is Codex-native; tests need to decide whether they still make sense, or assert on `"wave-a-lead"` for Claude-coordinated Wave A/B). Do not delete tests to make CI green. Where a test asserts an invariant that no longer holds under the new roster (e.g. "all six old leads registered"), rewrite the invariant against the new four-lead roster with an explanatory docstring update.
2. **Fix the walker-sweep line-number drift** (§6.2): update `tests/test_walker_sweep_complete.py:111` from 7702 to 7696.
3. **Rewrite history into three commits** per `phase-1-impl.md`'s directions:
   - Task 1.1 commit: roster rename + config field rename + migrated tests (`test_phase_lead_roster.py`, migrations to backend/integration/simulation).
   - Task 1.2 commit: `MESSAGE_TYPES` additions + `test_phase_lead_messaging.py`.
   - Task 1.3 commit: `codex_lead_bridge.py` + `test_codex_lead_bridge.py`.
   Since the work is on a local branch 1 commit ahead of origin and not yet published, an interactive history edit (`git reset --soft HEAD^` then three commits) is safe. Do not force-push to a published branch without explicit authorization.
4. **Re-run the full sanity sweep** (`python -m pytest tests/ -x --ignore=tests/test_v18_smoke --ignore=tests/test_carry_forward_c_cf.py -q`) and paste the exit-0 tail into the re-review request. `test_carry_forward_c_cf.py` can be temporarily ignored — it fails on master due to missing `v18 test runs/build-l-gate-a-20260416/.agent-team/` fixtures unrelated to Phase 1.

---

## 9. Summary

Phase 1 is **code-correct** and **prompt-correct**: the four-lead roster, six-field config, 13-entry message set, and `codex_lead_bridge` module all match the spec exactly, with good fail-open discipline and a well-written test for each new surface. The implementer clearly read the brief and executed the narrow-gate requirements well.

The failure is one of *scope control*: the implementer ran only the migrated test files listed in the plan (701 passes across those suites) and stopped, instead of running the full sweep that would have surfaced the 18 stale legacy-name assertions elsewhere in the suite. The brief warns about exactly this ("do not delete the test to make CI green") — nine test files still encode the pre-rename worldview and now fail. Plus the commit-history bundling violates criterion #10.

Both issues are readily fixable (stale-string migrations are mechanical; history rewrite is cheap on an unpublished branch). Once remediated, I expect this phase will accept cleanly.

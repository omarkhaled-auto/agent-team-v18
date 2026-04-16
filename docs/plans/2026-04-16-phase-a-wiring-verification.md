# Phase A Wiring Verification

**Author:** Wave 3b wiring-verifier
**Date:** 2026-04-16
**Branch:** phase-a-foundation
**Input:** Wave 2 edits applied; preserved artifacts in `v18 test runs/build-l-gate-a-20260416/.agent-team/`
**Scope:** Read-only verification that each Phase A code change fires on the production call path, not merely in unit tests.

---

## Summary verdict matrix

| Change | File:line (post-Wave 2) | Verdict | Notes |
|--------|--------------------------|---------|-------|
| N-01 port precedence | `endpoint_prober.py:1023-1055` | **PASS** | Single caller chain → Wave B probing fires the fix |
| N-01 loud fallback | `endpoint_prober.py:1050-1055` | **PASS** | `logger.warning` reached; `logger` already module-scope |
| N-15 to_json extras | `audit_models.py:277-291` | **PASS** (default config), **PARTIAL** when `v18.evidence_mode != "disabled"` + scope partitioning fires |
| NEW-7 save_state invariant | `state.py:521-597` | **PASS** | Offline replay of build-l's STATE raises correctly |
| cli.py silent-swallow fix | `cli.py:13491-13508` | **PASS** | `print_warning` replaces bare pass; import in scope at line 87 |
| NEW-8 from_json dropped IDs | `audit_models.py:362-382` | **PASS** | Reached by `state.py:153`, `cli.py:5398`, `cli.py:5868` |

**Overall**: PASS, with one pre-existing design gap flagged (not in N-15 scope) and one intended behavior change worth calling out (NEW-7 fails loud mid-pipeline on first milestone failure).

---

## Trace 1 — N-01 `_detect_app_url` precedence

### Callers

Only one call site in `src/` (`src/agent_team_v15/endpoint_prober.py:694`):

```
DockerContext(app_url=_detect_app_url(project_root, config))
```

No other production callers. `_detect_app_url` is a module-private helper.

### Production call graph (bottom-up)

| Level | File:line | Role |
|-------|-----------|------|
| leaf | `endpoint_prober.py:1023` | `_detect_app_url` (the fix site) |
| 1 | `endpoint_prober.py:694` | `start_docker_for_probing` — constructs `DockerContext(app_url=…)` |
| 2a | `wave_executor.py:1624` | `_run_wave_b_probing` imports + calls `start_docker_for_probing` |
| 2b | `fix_executor.py:723` | `_rerun_probes_for_acs_async` also calls it (regression-probe rerun path) |
| 3 | `wave_executor.py:2927`, `wave_executor.py:3448` | `_run_wave_b_probing` invoked from inside `_execute_milestone_waves_with_stack_contract` when `wave_letter == "B"` AND `_live_endpoint_check_enabled(config)` AND `wave_result.success` |
| 4 | `wave_executor.py:2644` | `execute_milestone_waves` — public entry, delegates to `_with_stack_contract` |
| 5 | `cli.py:3417` / `cli.py:4028` | `await execute_milestone_waves(…)` — fires per milestone during PRD-mode execution |
| 6 | `cli.py:3652` | `for milestone in ready:` — the main per-milestone loop inside `_run_prd_milestones` |
| 7 | `cli.py:10343` | `asyncio.run(_run_prd_milestones(…))` from CLI entry |

### Behavior against `apps/api/.env.example` containing `PORT=4000`

Walking `_detect_app_url(project_root, config)` where `project_root` points at a repo with `apps/api/.env.example` containing `PORT=4000`:

1. `config.browser_testing.app_port` — stock v18 config.yaml ships `browser_testing.app_port: 0` → falls through.
2. `<root>/.env` — stock PRD fixture does not create one → `_port_from_env_file` returns `None`.
3. `<root>/apps/api/.env.example` — `_port_from_env_file` matches `^\s*PORT\s*=\s*(\d+)\s*$` (MULTILINE) on the `PORT=4000` line and returns `4000`.
4. Returns `"http://localhost:4000"`.

Nothing layered above forces a different URL. `start_docker_for_probing` stores the returned string on `DockerContext.app_url` (`endpoint_prober.py:694`) and `_poll_health(context.app_url, …)` polls that exact URL (`endpoint_prober.py:756`). The probe will hit `:4000`, matching what the backend actually binds.

### Loud fallback reachability

`endpoint_prober.py:1050-1055`:

```python
logger.warning(
    "endpoint_prober: no PORT detected in config.browser_testing.app_port, "
    ".env, apps/api/.env.example, apps/api/src/main.ts, or docker-compose.yml; "
    "falling back to http://localhost:3080 (N-01)"
)
return "http://localhost:3080"
```

- `logger` exists at module scope (already referenced from many functions in this file, e.g., `endpoint_prober.py:705, 728, 753, 1050`). No import delta required.
- Fallback is reachable: when all five sources miss, the warning fires and the legacy port is returned. Matches arch-report §3.2 row 6.

### Remaining `localhost:3080` in source (outside `_detect_app_url`)

- `browser_test_agent.py:21` — **docstring example** (benign).
- `browser_test_agent.py:898` — `BrowserTestEngine(app_url: str = "http://localhost:3080", …)` default. **Benign in production**: both production construction sites pass an explicit `app_url`:
  - `coordinated_builder.py:1847` uses `f"http://localhost:{app.port}"` from `AppLifecycleManager`.
  - `cli.py:7903` uses `f"http://localhost:{args.port}"` from CLI argparse.
- `app_lifecycle.py:14` — **docstring example** (benign).
- `endpoint_prober.py:1053` and `:1055` — the N-01 loud fallback itself (intentional).

No orphan hardcoded `:3080` in the runtime-verification hot path. Verdict: **PASS**.

---

## Trace 2 — N-15 `AuditReport.to_json` extras preservation

### Callers of `to_json`

7 callers in `src/` (grep `\.to_json\(` in `src/agent_team_v15/`):

| File:line | What is written | Uses N-15 patched `to_json`? |
|-----------|-----------------|-------------------------------|
| `cli.py:6033` | `.agent-team/AUDIT_REPORT.json` (Producer 2 path) | **YES — primary production target** |
| `cli.py:5141` | `INTEGRATION_REPORT.json` (via `integration_report.to_json()`) | Yes, covers any AuditReport-shaped integration artefact |
| `coordinated_builder.py:631`, `:1230`, `:1311` | `audit_runN.json` (per-cycle artefacts, NOT AUDIT_REPORT.json — see comment at `coordinated_builder.py:694`) | Yes |
| `_audit_worker.py:62` | per-worker auditor dump | Yes |
| `config_agent.py:178` | different dataclass (config artifact), not AuditReport | N/A |

No other writer bypasses `to_json` for `AUDIT_REPORT.json`. No `json.dumps(asdict(report))` pattern found in `src/` (grep `json\.dumps.*asdict.*[Rr]eport` → 0 matches).

### Production write path (cli.py:6033)

Production flow that exercises Producer 2 (Python rewrite):

1. Scorer sub-agent runs per milestone (prompt at `audit_prompts.py:1349, 1352`) and writes `.agent-team/AUDIT_REPORT.json` in raw scorer shape (**Producer 1** — LLM direct tool-call; does NOT go through `to_json`).
2. `_run_milestone_audit` at `cli.py:5394-5398` reads that file back via `AuditReport.from_json`. Permissive parser captures unknown top-level keys into `report.extras` (audit_models.py:353).
3. `_apply_evidence_gating_to_audit_report` at `cli.py:530-651` may rebuild via `build_report` at `audit_models.py:730` **only when `_evidence_mode_enabled(config)`** (`cli.py:538`, which requires `config.v18.evidence_mode != "disabled"`). The rebuild drops extras because `build_report` doesn't propagate them.
4. `_run_milestone_audit_with_reaudit` at `cli.py:5868` may re-read on resume via `from_json` (same extras behavior).
5. Final write at `cli.py:6033`: `report_path.write_text(current_report.to_json(), encoding="utf-8")`. **This is where N-15 takes effect.**

### Path coverage given N-15

N-15 spreads `**self.extras` FIRST in the JSON dict at `audit_models.py:277-291`, so canonical fields win on collision.

| Scenario | Extras survive to disk? | Why |
|----------|-------------------------|-----|
| Default config (`evidence_mode: disabled`) — reaudit fires, no rebuild | **YES** | `_apply_evidence_gating_to_audit_report` short-circuits at `cli.py:538`; `report` is the original from_json output with extras intact; `to_json` now emits them |
| `evidence_mode != "disabled"` AND evidence-gate actually flips a verdict AND milestone scope partitioning fires | **NO — pre-existing gap** | `build_report` at `cli.py:639` constructs a fresh `AuditReport(**kwargs)` with no `extras`; N-15 has nothing to spread. Out-of-scope for N-15 (arch-report §1.2 step 3 identifies this; an N-15-like fix on `build_report` would close it) |
| Reaudit loop never enters (milestone failed at Wave B before audit phase, e.g., build-l) | **N/A** | `cli.py:6033` never runs; on-disk file remains Producer 1's untouched raw output |

### Build-l evidence

`v18 test runs/build-l-gate-a-20260416/.agent-team/AUDIT_REPORT.json` is Producer 1 shape (14 top-level scorer-only keys observed: `schema_version, generated, milestone, audit_cycle, overall_score, max_score, verdict, threshold_pass, auditors_run, raw_finding_count, deduplicated_finding_count, pass_notes, summary, score_breakdown, dod_results, by_category`). Python rewrite never fired because milestone-1 failed at Wave B (build-l `STATE.json` `wave_progress.milestone-1.failed_wave == "B"`) before the audit cycle reached `cli.py:6033`.

### Replay check

Offline replay confirmed via a Python round-trip against build-l's preserved file:

```
from_json(build-l AUDIT_REPORT.json)
  → extras keys: [auditors_run, by_category, deduplicated_finding_count, dod_results,
                   generated, milestone, overall_score, pass_notes, raw_finding_count,
                   schema_version, score_breakdown, summary, threshold_pass, verdict]
  → fix_candidates normalized from strings to int indices [0, 1, 4, 20, 27] (all resolved)
to_json(report)
  → written keys now include all 14 scorer keys PLUS canonical fields
    (canonical fields: acceptance_tests, audit_id, auditors_deployed, by_file,
     by_requirement, by_severity, cycle, findings, fix_candidates, score, scope, timestamp).
```

Verdict: **PASS** for the default-config production path. **PARTIAL** gap flagged for `evidence_mode != "disabled"` + scope-partition rebuild — pre-existing, not in N-15 scope.

---

## Trace 3 — NEW-7 `save_state` invariant

### Invariant site

`state.py:584-597`:

```python
_expected_success = (not state.interrupted) and len(state.failed_milestones) == 0
if bool(data["summary"].get("success")) != _expected_success:
    raise StateInvariantError(…)
```

Placed after summary assembly (`state.py:569-582`) and before the atomic tempfile write (`state.py:601-614`), so a partial tempfile is never left on disk on violation.

### Callers of `save_state`

24 call sites in `src/agent_team_v15/` (module-level function; `state.py:521`):

| File:line | Local wrap | Outer handler |
|-----------|------------|---------------|
| `cli.py:1026` | `try/except Exception` at `:1016-1028` (returns "") | — |
| `cli.py:1079` (`_save_wave_state`) | no local wrap | Caller-controlled; `_save_wave_state` is invoked from `save_wave_state=` callback — see below |
| `cli.py:1118` (`_save_isolated_wave_state`) | no local wrap | Caller-controlled; `_persist_worktree_wave_state` callback |
| `cli.py:3015` | `try/except Exception: pass` at `:3013-3017` | PROTECTED locally |
| `cli.py:3621` | — | **Protected by outer `except Exception` at `cli.py:10415`** inside `_run_prd_milestones`/async_main |
| `cli.py:3709` | — | Outer `cli.py:10415` |
| `cli.py:3739`, `:3755`, `:3782` | — | Outer `cli.py:10415`; preceded by `update_milestone_progress(..., "FAILED"/"BLOCKED")` |
| `cli.py:4083`, `:4119` | inside except handlers at `:4100-4120` and `:4061-4084` | Outer `cli.py:10415`; these are the timeout/failure catch bodies |
| `cli.py:4431`, `:4551`, `:4566`, `:4674`, `:4706`, `:4824`, `:4883` | — | Outer `cli.py:10415` |
| `cli.py:7586` | `try/except Exception` at `:7581-7589` (double-interrupt path) | PROTECTED locally |
| `cli.py:9343` | `try/except Exception: pass` at `:9341-9345` | PROTECTED locally |
| `cli.py:10450` | `try/except Exception: pass` at `:10448-10452` | PROTECTED locally; this is the **post-orchestration state save** |
| `cli.py:13506` (`_save_final`) | outer `try/except` at `:13483-13508` logs via `print_warning` | PROTECTED by D-13 follow-up fix |

### Outer handler detail

`cli.py:10415` (the async_main orchestration body):

```python
except Exception as exc:
    print_warning(f"Orchestration interrupted: {exc}")
    if _current_state:
        _current_state.interrupted = True
        _current_state.error_context = str(exc)
        run_cost = _current_state.total_cost
```

Any `StateInvariantError` escaping from `_run_prd_milestones` is caught here. `_current_state.interrupted` is set `True`, and the next `save_state` at `cli.py:10450` will satisfy the invariant (because `_expected_success = not True and … = False` and `finalized.get("success", not True) = False` — match).

### Intended behavior change (flag, not gap)

Per `tests/test_state.py:646-659` `test_failed_milestone_with_clean_summary_still_ok`, the invariant is **designed to raise** even when `state.summary` is empty, because `finalized.get("success", not state.interrupted)` defaults to `True` while `_expected_success` is `False`.

Practical effect on the PRD pipeline: the FIRST mid-pipeline `save_state` call that runs after a milestone enters `failed_milestones` (e.g., `cli.py:4119` in the milestone-loop `except Exception` handler) will raise. The raise propagates out of the for-loop, past `_run_prd_milestones`, to the outer catch at `cli.py:10415` → pipeline halts early with `interrupted=True`.

This matches the NEW-7 intent (fail loud rather than silently write a lie) and matches the build-l pathology (wrote success=True with failed_milestones=['milestone-1']). Call it out in the Phase A report so operators expect pipelines to abort early on the first milestone failure — which is the desired behavior for the build-l vector.

**Workaround if pipelines need to continue past individual milestone failures**: the milestone-loop except handlers at `cli.py:4083, :4119` (and peers) could call `state.finalize()` before `save_state` so `state.summary["success"]` is correctly populated. Not in Phase A scope; listed for the author of Phase A follow-up.

### Unprotected-caller check for `_save_wave_state` / `_save_isolated_wave_state`

These wrappers (`cli.py:1032-1079`, `cli.py:1082-1118`) have no local try/except around their internal `save_state`. They are invoked via callback (`save_wave_state=` parameter on `execute_milestone_waves`). Callback is called from `wave_executor.py` inside Wave steps. Any raise bubbles up through `execute_milestone_waves` → `await asyncio.wait_for(...)` at `cli.py:3416` or `:4057` → caught by outer `cli.py:10415`. Protected through the outer catch chain.

### Replay check

Offline replay: loaded build-l's STATE.json via current `state.load_state`, then called `state.save_state` on the loaded state:

```
loaded: interrupted=False failed=['milestone-1'] summary.success=True
save_state: RAISED StateInvariantError (CORRECT)
  detail: STATE.json invariant violation: summary.success=True but interrupted=False,
           failed_milestones=['milestone-1'] (expected success=False). Likely cause:
           finalize() was not called or threw silently. See cli.py:13491-13498.
```

Verdict: **PASS**. Build-l's pathological state cannot silently escape through any `save_state` path. Mid-pipeline raises surface through the outer `cli.py:10415` catch → final post-orchestration save writes the correct `success=False` with `interrupted=True`.

---

## Trace 4 — cli.py:13491 silent-swallow replacement

### Block (post-Wave 2) at `cli.py:13483-13508`

```python
try:
    from .state import save_state as _save_final
    # D-13: reconcile aggregate fields before final save
    try:
        _current_state.finalize(
            agent_team_dir=Path(cwd) / ".agent-team"
        )
    except Exception as exc:
        # D-13 follow-up: do NOT silent-pass.
        print_warning(
            f"[STATE] finalize() raised before final STATE.json write: "
            f"{type(exc).__name__}: {exc}. "
            f"summary.success may be derived from legacy defaults. "
            f"Inspect failed_milestones / interrupted manually."
        )
    _save_final(_current_state, directory=str(Path(cwd) / ".agent-team"))
except Exception as exc:
    print_warning(f"[STATE] Final save_state() failed: {type(exc).__name__}: {exc}")
```

### Verification

- Uses `print_warning` (convention — `log.warning` is not used for operator-visible output in this codebase; `print_warning` is imported at `cli.py:87`).
- `print_warning` is in module scope at line 13491 (import is at module top: `from .ui_output import ... print_warning ...` per grep).
- Outer `try` at `:13483-13508` preserved, so a `finalize` throw still lets `save_state` run (doesn't regress to "not-writing STATE at all on finalize throw").
- Inner throw path now logs LOUD (was silent `except Exception: pass`). Confirmed grep within `cli.py:13480-13510` shows no remaining bare `except Exception: pass`.
- Outer except also now `print_warning`-logs (was also silent). Both silent-swallows replaced.

Verdict: **PASS**.

---

## Trace 5 — NEW-8 `from_json` dropped-IDs warning

### Warning site

`audit_models.py:372-382` (inside `AuditReport.from_json`):

```python
if dropped:
    import logging
    logging.getLogger(__name__).warning(
        "AuditReport.from_json: %d fix_candidate id(s) dropped "
        "(absent from findings): %s. Total findings=%d, candidates kept=%d. (NEW-8)",
        len(dropped),
        dropped[:10] + (["..."] if len(dropped) > 10 else []),
        len(findings),
        len(fix_candidates),
    )
```

Fires only when `raw_fix_candidates[0]` is a `str` (scorer shape) AND at least one ID is absent from `findings`.

### Callers of `AuditReport.from_json`

| File:line | Role |
|-----------|------|
| `state.py:153` | `State.finalize` reads `AUDIT_REPORT.json` to populate `audit_health` |
| `cli.py:5398` | `_run_milestone_audit` reads scorer-produced AUDIT_REPORT.json each cycle |
| `cli.py:5868` | `_run_milestone_audit_with_reaudit` resume guard reads existing AUDIT_REPORT.json |

No other `AuditReport.from_json` callers in `src/`.

### Build-l path exercise

Build-l's preserved `AUDIT_REPORT.json` ships `fix_candidates` as 25 string IDs. All 25 resolve to findings in the file; offline replay confirmed 0 dropped IDs → NEW-8 warning does NOT fire for build-l itself.

### Scenarios where NEW-8 would fire

- Scorer emits `fix_candidates: ["F-001", "F-002"]` but dedupe at `from_json` dropped "F-002" before indexing (dedup path in `deduplicate_findings` at `audit_models.py:660`+).
- Stale IDs referencing a prior cycle's findings (resume scenarios).
- Handwritten / malformed test fixtures.

Confirmed reachable: each of the three callers above reads a scorer-produced AUDIT_REPORT.json whose `fix_candidates` is list-of-strings (per the D-07 permissive contract). NEW-8's warning fires at the first from_json invocation to observe unresolvable IDs. Multiple callers may fire the warning multiple times for the same file — not deduplicated, which is acceptable (operators see one per read attempt).

Verdict: **PASS**.

---

## Trace 6 — Build-l offline replay simulation

End-to-end behavior under current code when reading build-l's preserved artifacts:

1. **Load AUDIT_REPORT.json via `AuditReport.from_json`** (e.g., from `state.py:153` inside `finalize`):
   - Extras populated with 14 scorer keys (`verdict`, `health` presumably absent since build-l uses top-level `verdict` only; checked — `extras` includes `verdict: "FAIL"` and the rest).
   - `fix_candidates` normalized from `["AUD-001", "AUD-002", …]` to int indices `[0, 1, 4, 20, 27]`. All 25 IDs resolve; NO NEW-8 warning for build-l.
   - `health` on extras: build-l doesn't ship a top-level `"health"` key — instead `verdict: "FAIL"`. `State.finalize` at `state.py:158-162` reads `extras.get("health") or ""` (empty) then falls back to `report.score.health`. `score.health` is populated by `AuditScore.compute` or passed-through when `health=data.get("health", "")` is empty. Net effect: `state.audit_health` stays empty from build-l. Acceptable: the on-disk `verdict` is still preserved in extras for downstream inspection.

2. **Load STATE.json via `state.load_state`, then re-save via `state.save_state`**:
   - Loaded: `interrupted=False, failed_milestones=['milestone-1'], summary.success=True` (the build-l pathology).
   - `save_state` raises `StateInvariantError` — confirmed by running the replay Python above.
   - Invariant message: `"STATE.json invariant violation: summary.success=True but interrupted=False, failed_milestones=['milestone-1'] (expected success=False). Likely cause: finalize() was not called or threw silently. See cli.py:13491-13498."`

3. **Pipeline semantics**: If the same build-l scenario re-ran under current code, the first `save_state` call after milestone-1 was marked FAILED (at `cli.py:4119` or peer) would raise → caught by outer `cli.py:10415` → `interrupted=True` set → pipeline exits milestone loop → post-orchestration at `cli.py:10450` saves successfully with `success=False`. The silent-swallow that produced build-l's state is no longer reachable.

4. **Finalize throw path**: If `finalize` throws at `cli.py:13491`, the D-13 follow-up (`cli.py:13500-13505`) now emits a loud `print_warning` citing the exception type/message. `save_state` then runs at `cli.py:13506`; if `state.summary.success` was left inconsistent by the partial finalize, NEW-7 fires and the outer `except` at `:13507` logs that too via `print_warning`.

Verdict: **PASS** end-to-end. Build-l's silent-write pathology is now loud at every boundary.

---

## Trace 7 — Coverage gap assessment

### AUDIT_REPORT.json writers (grep `AUDIT_REPORT\.json` in `src/`)

- `audit_prompts.py:1349, 1352` — scorer prompt instructing the LLM to write. Producer 1, not via `to_json`.
- `cli.py:6033` — Producer 2, uses N-15 patched `to_json`. **This is the only Python writer**.
- Other matches are **readers** (`cli.py:5394, 5865, 12630`; `state.py:142`; `hooks.py:164, 169`; `skills.py:286` via `_read_audit_findings` uses plain `json.loads` and does not re-write).

No other writer bypasses `AuditReport.to_json` for `AUDIT_REPORT.json`. Confirms arch-report §1.4.

### `state.summary["success"]` mutations (grep in `src/`)

- `state.py:135` (`self.summary["success"] = …` inside `finalize`).
- `state.py:339` (module docstring).

`save_state` at `state.py:569` WRITES `data["summary"]["success"]`, but reads from `finalized.get("success", …)` — it does not mutate `state.summary` itself. Read-only with respect to live state.

No orphan mutations of `state.summary["success"]` anywhere else in `src/`. Confirmed single-source-of-truth (`finalize` is the only writer; `save_state` is read-only + invariant-check).

### Thread / background-task reachability

Grep for `Thread(`, `ThreadPool`, `asyncio.create_task`, `run_in_executor` in `cli.py`: present, but none of the matches co-occur with `save_state`. No background-thread code path invokes `save_state` where a raised `StateInvariantError` could escape uncaught.

### `_apply_evidence_gating_to_audit_report` extras-drop (flagged)

`cli.py:639` via `build_report` (`audit_models.py:730`): `build_report` constructs a fresh `AuditReport` **without propagating `extras`**. When `config.v18.evidence_mode != "disabled"` AND scope partitioning actually fires, N-15's extras-preservation is nullified for that milestone's re-written report.

- Default config: `evidence_mode: "disabled"` → `_apply_evidence_gating_to_audit_report` short-circuits at `cli.py:538` → extras survive → N-15 takes effect on write.
- Non-default config with evidence mode on AND a verdict actually flipped: extras lost in rebuild.

Pre-existing gap, identified in arch-report §1.2 step 3 (and §6.4 "production-path wiring confidence"). Not in N-15 scope. A follow-up fix would be trivial: make `build_report` accept an `extras` kwarg and set it on the returned `AuditReport`, or have `_apply_evidence_gating_to_audit_report` re-attach `report.extras` onto the rebuilt instance.

Recommendation to team-lead (do not fix autonomously per task constraint): file a follow-up ticket "extras propagation through build_report" as a NEW-## follow-up to N-15. Scope: 5-line change + 1 unit test.

### Summary

No unsurfaced orphan writers, no orphan state mutations, no background-thread leaks, no silent-swallow paths remaining. The one flagged gap (`build_report` extras drop) is **out-of-scope for Phase A** and does not affect the default-config production path.

---

## Behavior change call-outs for Phase A report

1. **NEW-7 aborts pipelines on first milestone failure under default summary state.** This is `test_state.py:646-659`'s contract and matches the intent (fail loud rather than silently lie about success). Operators running "continue past individual milestone failures" semantics should call `state.finalize()` before mid-pipeline `save_state` calls — or accept that a single milestone failure now halts the run cleanly with `interrupted=True` and `success=False`. Out-of-scope fix path if the prior semantics are preferred.

2. **`evidence_mode != "disabled"` drops N-15 extras on scope-partition rebuild.** Pre-existing gap through `build_report`. Not introduced by Phase A; flagged here because arch-report §6.4 asked wiring-verifier to spot it. Trivial follow-up fix available.

---

## Verdict

**PASS** — all six Phase A changes are correctly wired into the production call path. Two items flagged:

- `evidence_mode` + scope-partition extras drop → pre-existing gap, out-of-scope for Phase A, file follow-up ticket.
- NEW-7 now halts pipelines on first milestone failure (under default summary state) → working as designed per test contract; recommend calling this out in PHASE_A_REPORT.md so operators expect the new behavior.

No fixes applied (task constraint: read-only).

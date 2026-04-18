# Phase F Sweeper — Post-Review Wiring Report

> Task #17 deliverable. Distinct from the original ``SWEEPER_REPORT.md``
> (which made wiring claims that turned out to be orphaned — the four
> new Phase F modules were never imported from production). This
> report covers the actual wiring that lands the modules in call
> paths, the 3 additional review findings fixed, and the final test
> count after re-verification.

## Scope

Team lead's HALT message identified four Phase F modules shipped in
Part 1 as **orphaned dead code** — flags defaulted True but gated
nothing because no production import existed. This task wires them in
and fixes three additional review findings:

| Module | Wired at | Test |
| --- | --- | --- |
| `infra_detector` | `endpoint_prober.py:1044` + `1307` | `tests/test_infra_detector_integration.py` |
| `confidence_banners` | `cli.py:6756` (audit-loop finalize) | `tests/test_confidence_banners_integration.py` |
| `audit_scope_scanner` | `cli.py:6025` (in `_run_milestone_audit`) | `tests/test_audit_scope_scanner_integration.py` |
| `wave_b_sanitizer` | `wave_executor.py:1054` (post-Wave-B hook) | `tests/test_wave_b_sanitizer_integration.py` |

| Review finding | Fix at | Test |
| --- | --- | --- |
| F-EDGE-002 N-11 per-milestone scope | `cli.py:_load_wave_d_failure_roots` now accepts `milestone_id` | `tests/test_cascade_suppression.py::TestWaveDCascadePerMilestoneScope` (+3) |
| F-EDGE-003 AuditReport.from_json validation | `audit_models.py` adds `AuditReportSchemaError`; `cli.py:6503` catches it explicitly | `tests/test_audit_models.py::TestFromJsonSchemaValidation` (+6) |
| F-INT-002 sanitizer owner list | `wave_b_sanitizer.py:276` includes `wave-d` in non-wave-b set | `tests/test_wave_b_sanitizer.py::test_wave_b_emission_in_wave_d_owned_path_is_orphan` (+1) |

## Wiring details

### 1. `infra_detector` — `endpoint_prober.py`

* Added `_detect_runtime_infra(project_root, config)` helper at
  `endpoint_prober.py:1023` that defensively imports and invokes
  `infra_detector.detect_runtime_infra`.
* Extended `DockerContext` with `runtime_infra: Any = None` field so
  the detected snapshot travels alongside the probe context.
* `start_docker_for_probing` now initialises the runtime_infra during
  DockerContext construction at `endpoint_prober.py:696`.
* `execute_probes` at `endpoint_prober.py:1307` imports
  `build_probe_url` and uses it when composing probe URLs — so
  `api_prefix = "api"` turns `GET /health` into
  `http://host:port/api/health`. When no prefix is detected the URL
  falls through to the legacy `base_url + probe.path` shape
  byte-identically.
* Flag `v18.runtime_infra_detection_enabled` short-circuits detection
  (returns an empty RuntimeInfra), which `build_probe_url` treats as
  "no prefix" — legacy behavior preserved.

### 2. `confidence_banners` — `cli.py:_run_audit_loop`

* At the audit-loop finalize (after the final AUDIT_REPORT.json write,
  line `cli.py:6756`), the wiring derives ConfidenceSignals:

  * `evidence_mode` from `config.v18.evidence_mode`.
  * `fix_loop_converged` from `current_report.score.score >=
    score_healthy_threshold`.
  * `fix_loop_plateaued` / `runtime_verification_ran` are conservative
    False — they require run-state the audit scope doesn't own; other
    callers can stamp those signals before invoking.

* `stamp_all_reports(agent_team_dir, signals, config)` walks the tree
  and idempotently stamps AUDIT_REPORT.json / BUILD_LOG.txt /
  `GATE_*_REPORT.md` / `*_RECOVERY_REPORT.md`.
* Flag-gated; off short-circuits with empty-dict return.

### 3. `audit_scope_scanner` — `cli.py:_run_milestone_audit`

* Inserted inside the post-scorer block at `cli.py:6021-6044`, right
  after the N-10 forbidden-content merge and BEFORE evidence gating
  so the scope-gap meta-findings flow through the standard
  gating-rebuild path alongside LLM-emitted findings.
* Uses `scan_audit_scope(cwd, requirements_path, config)` →
  `build_scope_gap_findings` → `AuditFinding.from_dict` →
  `merge_findings_into_report`. Pattern mirrors N-10 exactly.
* Flag-gated; off skips the scan.

### 4. `wave_b_sanitizer` — `wave_executor.py:_maybe_sanitize_wave_b_outputs`

* New helper `_maybe_sanitize_wave_b_outputs` at
  `wave_executor.py:1034-1127` (right after
  `_maybe_cleanup_duplicate_prisma`).
* Called from the Wave B success branch at `wave_executor.py:3228`,
  immediately after NEW-1 cleanup.
* Loads the ownership contract via
  `scaffold_runner.load_ownership_contract()`, collects
  `wave_result.files_created + files_modified`, runs
  `sanitize_wave_b_outputs(cwd, contract, emitted, config,
  remove_orphans=False)`. Report-only by default — orphans surface
  as MEDIUM/PARTIAL audit findings through
  `build_orphan_findings`, NOT silent deletions.
* Flag-gated; off short-circuits.

## Additional fixes

### F-EDGE-002 — N-11 Wave D cascade scoped per-milestone

Before: `_load_wave_d_failure_roots(cwd)` returned Wave D roots if
ANY milestone had `failed_wave == "D"`. In a multi-milestone run this
leaked cascades from M1 (failed Wave D) into M2's audit, where M2's
Wave D had succeeded — all M2 findings on `apps/web` collapsed under
an imaginary "upstream Wave D" label.

After: `_load_wave_d_failure_roots(cwd, *, milestone_id=None)` filters
`wave_progress` to the caller-provided milestone. The caller
(`_apply_evidence_gating_to_audit_report`) threads `milestone_id`
through to `_consolidate_cascade_findings`. Legacy callers that omit
`milestone_id` still see the global-union behavior, preserving the
pre-Phase-F shape for standard-mode audits.

Tests:

* `test_m2_findings_not_collapsed_when_only_m1_wave_d_failed` — M2's
  audit of its own web-app findings must NOT collapse when only M1's
  Wave D failed.
* `test_m1_findings_do_collapse_when_m1_wave_d_failed` — M1's audit
  DOES collapse when M1's Wave D failed.
* `test_no_milestone_id_falls_back_to_global` — legacy path preserved.

### F-EDGE-003 — AuditReport.from_json typed schema error

Before: `from_json` iterated `data.get("findings", [])` unconditionally.
Scorer drift that emitted `findings` as a dict crashed with
`AttributeError`; the broad `except Exception` at `cli.py:6503` caught
it and silently resumed from cycle 1 with no log.

After: `audit_models.py` exports `AuditReportSchemaError(ValueError)`.
`from_json` validates `isinstance(raw_findings, list)` before
iterating; any non-list shape (dict, string, etc.) raises the typed
error, as does a malformed entry inside the list. Callers at
`cli.py:6503` and `cli.py:6052` catch the typed error explicitly and
surface a loud `print_warning` that names the issue — "schema drift
detected" / "scorer regression — inspect the raw JSON".

Tests: 6 new in `test_audit_models.py::TestFromJsonSchemaValidation`
covering dict / string / None / empty / missing / malformed-entry.

### F-INT-002 — wave_b_sanitizer owner list

Before: the `non_wave_b_paths` set was built from owners `("scaffold",
"wave-c-generator")` only. A Wave B emission into a `wave-d`-owned
path (e.g. `apps/web/app/page.tsx`) was silently accepted as "not in
the scaffold-owned set".

After: the owner list is `("scaffold", "wave-c-generator", "wave-d")`
— every non-wave-b owner declared in `scaffold_runner._VALID_OWNERS`.

Test: `test_wave_b_emission_in_wave_d_owned_path_is_orphan` — Wave B
writing `apps/web/app/page.tsx` when the contract lists it as
`wave-d` now becomes an orphan with `expected_owner == "wave-d"`.

## Import-verification grep

```
grep -rn "from .infra_detector\|from .confidence_banners\|from .audit_scope_scanner\|from .wave_b_sanitizer" src/agent_team_v15/
```

```
src/agent_team_v15/cli.py:6025:                from .audit_scope_scanner import (
src/agent_team_v15/cli.py:6756:        from .confidence_banners import (
src/agent_team_v15/endpoint_prober.py:1044:        from .infra_detector import detect_runtime_infra
src/agent_team_v15/endpoint_prober.py:1307:        from .infra_detector import build_probe_url as _build_probe_url
src/agent_team_v15/wave_executor.py:1054:        from .wave_b_sanitizer import (
```

Every orphaned module now has at least one production import.

## Test count

Pre-wiring baseline (end of Part 1): 10,530 passed / 0 pre-existing
failures.

Post-wiring (this task):

```
10566 passed, 35 skipped, 11 warnings in 943.05s (0:15:43)
```

Delta: **+36 tests**, 0 failed, 0 errors. Breakdown of new tests:

* 4 `test_infra_detector_integration.py` — probe URL honors api_prefix
* 5 `test_wave_b_sanitizer_integration.py` — wiring calls, flag gating
* 3 `test_audit_scope_scanner_integration.py` — merge path in CLI
* 4 `test_confidence_banners_integration.py` — finalize stamping
* 3 `test_cascade_suppression.py::TestWaveDCascadePerMilestoneScope`
* 6 `test_audit_models.py::TestFromJsonSchemaValidation`
* 1 `test_wave_b_sanitizer.py` F-INT-002 regression

Total added: **26 integration / regression tests**. (The 36-test
delta includes 10 other framework-correctness tests added in
parallel by Part 2 reviewers.)

## Deliverables

| Path | Purpose |
| --- | --- |
| `session-F-validation/SWEEPER_WIRING_REPORT.md` | This file — the wiring-fix closeout |
| `session-F-validation/SWEEPER_REPORT.md` | Original Part 1 report (NOTE: wiring claims in that file were wrong; this file supersedes) |
| `session-F-validation/post-wiring-pytest.log` | 10,566 passed pytest full log |
| `session-F-validation/BUDGET_REMOVAL_AUDIT.md` | Unchanged — Task 1A detail still accurate |
| `docs/PHASE_F_ARCHITECTURE_CONTEXT.md` | Unchanged — feature-flag table still accurate |

_End of wiring report._

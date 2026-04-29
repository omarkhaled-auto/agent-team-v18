---
name: Phase 5.9 pipeline-upgrade landing
description: As-shipped state of Phase 5.9 (milestone AC-count cap 10 + auto-split with cap-2 chunking + flat <id>-a/-b/-c IDs + per-half REQUIREMENTS.md + non-canonical archive of original — R-#43 source-level closure); FINAL phase of v5
type: project
---

Phase 5.9 of the 9-phase Phase 5 plan landed direct-to-master on
2026-04-29 off baseline `968e8d7` (Phase 5.8a reviewer corrections) as
two source commits: `229678d` (initial landing) + `34bab7a`
(reviewer-corrections — 2 split-edge blockers). Plan:
`docs/plans/2026-04-28-phase-5-quality-milestone.md` §L. R-#43
source-level closure; AC3 live M1+M2 smoke + 6-milestone synthetic are
operator-authorised activities deferred (per §O.4.15 / §O.4.16).
**Final source HEAD: `34bab7a`** (this landing memo lands as a
docs-only commit on top, so the repo HEAD will differ; consult
`git log --oneline` for the most recent reference).

Phase 5.9 is the **NINTH and FINAL** sub-phase of v5 per §0.3 Wave 4 —
after this lands, all 9 sub-phases of the v5 Phase 5 plan are shipped.

## Reviewer-correction defects closed (34bab7a)

Reviewer focused-repro after the `229678d` initial landing surfaced two
split-edge blockers; closed in `34bab7a` with 3 new lock tests. Total
fixture count rose from 45 → 48; targeted slice 1043 → 1046; wide-net
2291 → 2294. No regressions across any prior phase.

### 1. Re-split of an already-suffixed milestone produced nested IDs

Reviewer repro at `229678d`: an over-cap milestone whose ID was
already a Phase 5.9 split-half (e.g. `milestone-7-a` with 12 ACs)
split into `milestone-7-a-a` + `milestone-7-a-b`. Those nested IDs
round-trip through neither the parser regex nor the generator's
heading-num extraction (both shapes accept a SINGLE optional
`-<letter>` segment by design).

```
split_ids  = ['milestone-7-a-a', 'milestone-7-a-b']
md_headers = ['## Milestone milestone-7-a-a: ...', ...]
parsed_ids = []
```

Closed: new `_is_split_half_id(milestone_id)` helper detects
`-<letter>$` via `_SPLIT_HALF_ID_RE`. New pre-mutation guard 1b in
`split_oversized_milestones` walks input milestones; any over-cap
milestone whose ID already passes `_is_split_half_id` raises
`ValueError` BEFORE any in-memory rebuild or file mutation. The error
message names the offender + explains why nesting violates the flat
single-letter alphabet contract. Per the v3 approval, re-split-of-a-
split-half is treated as a structural defect.

Locked by:

* `test_split_rejects_already_suffixed_milestone_with_too_many_acs` —
  synthetic `milestone-7-a` with 12 ACs raises naming the offender.
* `test_split_at_max_split_halves_all_letters_unique_and_flat` —
  positive invariant: 26-half split emits flat single-letter
  alphabetical sequence (`-a` through `-z`), no duplicates, no
  multi-letter forms.

### 2. Multi-original archive race left half-mutated state on idempotency failure

Reviewer repro at `229678d`: multi-original split where a later
original already had its archive. The loop ran
`_archive_original_requirements` one-by-one, so an earlier original's
canonical `REQUIREMENTS.md` was already moved before `FileExistsError`
aborted.

```
raised             = FileExistsError
m7 canonical exists = False  # m7's canonical was moved
m7 archive exists   = True
m8 canonical exists = True   # m8's canonical not moved (archive blocked)
```

Closed: PREFLIGHT loop walks EVERY split original's archive target
BEFORE any `Path.rename` runs. If ANY archive already exists, raise
`FileExistsError` immediately with all offending paths in one
message — no canonical file is moved. Pre-mutation discipline now
extends end-to-end through the multi-original archive phase.

Locked by:

* `test_split_preflights_archives_no_canonical_moved_on_idempotency_failure` —
  multi-original input (m7 + m8), pre-create m8's archive. Asserts
  raises `FileExistsError` naming `milestone-8`, m7 canonical
  unchanged, m8 canonical unchanged, no half-files written.

The existing `test_split_idempotency_raises_on_existing_archive` still
passes (preflight raises in the single-original case too).

## Files touched (matches plan §L.1 + scope check-in extensions)

| File | Change |
|---|---|
| `src/agent_team_v15/milestone_manager.py` | All Phase 5.9 logic. (a) New constants `MILESTONE_AC_CAP_DEFAULT = 10` and `MAX_SPLIT_HALVES = 26` + archive-path constants; (b) `_RE_MILESTONE_HEADER` regex widened to accept suffixed IDs `\d+(?:-[a-z])?` with negative lookahead `(?![-a-z])` so `## Milestone 7-aa:` and `## Milestone 7-:` are rejected; (c) `_id_form` regex in `_parse_deps` widened identically so dependency edges referencing split halves (e.g. `milestone-7-b`) round-trip; (d) `generate_master_plan_md` heading-num extraction fixed for suffixed IDs (emits `## Milestone 7-a: Title`, not the broken `## Milestone milestone-7-a: Title`); (e) `validate_plan(..., *, ac_cap=None)` kwarg — gate at `> ac_cap` (error, not warning) when cap >= 3; legacy `<3` advisory floor preserved; foundation 0-AC milestones exempt; `ac_cap=0` disables gate (legacy unbounded — pre-Phase-5.9 `>13` warn restored as the only floor in that mode); (f) `split_oversized_milestones(milestones, *, cap, cwd=None)` — auto-split helper with cap-2 chunking (`emit cap-2 chunks while remainder > cap; final remainder may equal cap`); 26-half pre-mutation guard raises `ValueError` BEFORE any file mutation; downstream dependency rewrite to last-half ID; per-half `(Part N)` title; chained `M-b deps M-a, M-c deps M-b, ...`; archive helper moves canonical `REQUIREMENTS.md` → `<orig-id>/_phase_5_9_split_source/REQUIREMENTS.original.md`; per-half `_write_split_requirements_md` writes scoped active checklist with one `- [ ] AC-XXX (review_cycles: 0)` per assigned AC; idempotency guard — re-split with archive present raises `FileExistsError`. |
| `src/agent_team_v15/cli.py` | (a) Import `split_oversized_milestones` + `MILESTONE_AC_CAP_DEFAULT` from `milestone_manager`; (b) Insert auto-split call BEFORE `validate_plan` at the existing plan-validation site (cli.py post-`parse_master_plan` block); persist post-split shape via `generate_master_plan_json` + `generate_master_plan_md` so on-disk reflects in-memory; pass `ac_cap=_ac_cap` kwarg through to `validate_plan`; wrap split + persist exceptions (`ValueError` from over-26-half guard / `FileExistsError` from idempotency guard / `OSError` from disk persist) into the existing `RuntimeError` user-error path; emit `[Phase 5.9 §L: auto-split applied (cap=N); M milestone(s) post-split.]` info line when split fires. (c) New `--milestone-ac-cap N` argparse flag mirroring `--cumulative-wedge-cap` (default `None`, falls back to config; `0` disables; `1`/`2` rejected; `>= 3` active). (d) CLI override threading via `getattr(args, "milestone_ac_cap", None)` (legacy-Namespace robust). |
| `src/agent_team_v15/agents.py:6043` | One-line edit. `Maximum: 13 ACs (above this, split into sub-features)` → `Maximum: 10 ACs per milestone (the validator gates above this; auto-split is applied when the planner emits above-cap milestones)`. Surrounding sizing rules (Target 5-10, Minimum 3, Foundation 0) unchanged. |
| `src/agent_team_v15/config.py` | (a) `V18Config.milestone_ac_cap: int = 10` field; (b) YAML threading via `_coerce_int` block in the v18 config loader; (c) `_validate_v18_phase59(cfg)` — rejects `< 0` and `1`/`2`; allows `0` (disabled) and `>= 3` (active). Invoked after the v18 YAML block alongside `_validate_v18_phase57`. |
| `tests/test_v18_vertical_slice_fixes.py` | Two assertions updated to match Phase 5.9's new contract: `test_warns_on_oversized_milestone` now asserts both the new error path (default `ac_cap=10` → 14-AC milestone errors) AND the legacy preserve path (`ac_cap=0` → 14-AC milestone retains pre-Phase-5.9 `>13` warn); `test_prompt_has_sizing_rules` updated to `Maximum: 10 ACs per milestone`. |
| `tests/test_agents.py` | One assertion updated: `test_milestone_sizing_instruction` updated to `Maximum: 10 ACs per milestone`. |
| **NEW** `tests/test_pipeline_upgrade_phase5_9.py` | 48 fixtures (45 in `229678d` + 3 reviewer-correction locks in `34bab7a`). Driven by per-AC parametrization on the heuristic table + explicit suffix-policy + scanner-skip locks + split-edge guards. |
| `docs/plans/2026-04-28-phase-5-quality-milestone.md` | §O.4 closeout-evidence checklist appended with rows O.4.15 (post-Phase-5.9 M1 ≤ 10 ACs) and O.4.16 (6-milestone synthetic — backward-compat AC4). |

**Not touched** (per §0.1 invariant 15 + §M.M16 preserved decisions):

* Phase 1-3.5 primitives (anchor / lock / hook / ship-block) — preserved.
* Phase 4.x cascade primitives (owner_wave / wave_failure_forensics / lift / anchor-on-complete / wave_boundary) — preserved.
* Phase 5.{1,2,3,4,5,6,7,8a} primitives (score normalisation, audit-team plumbing, STATE.json quality-debt fields, cycle-1 dispatch + `_run_audit_fix_unified` + cost cap, Quality Contract single-resolver + sidecar + state-invariants + suppression registry, unified strict build gate + `unified_build_gate.run_compile_profile_sync`, bootstrap watchdog + productive-tool-idle + cumulative wedge cap, cross-package diagnostic + `CONTRACT-DRIFT-DIAGNOSTIC-001` advisory) — preserved.
* `cascade_quality_gate_blocks_complete` at `audit_team.py:161` — UNCHANGED.
* `_anchor/_complete/` directory name + `_quality.json` 6-field schema — preserved.
* `audit_fix_rounds` field name — preserved.
* `score_healthy_threshold` default 90 — preserved.
* `vertical_slice` planner_mode — preserved (only the cap line in the planner prompt edits).
* AUDIT_REPORT.json schema — unchanged.
* Quality Contract gate filters — unchanged. The cap fires at PLAN VALIDATION time, not at the Quality Contract terminal write.
* `audit_prompts.py` advisory exception for `CONTRACT-DRIFT-DIAGNOSTIC-001` — unchanged.
* Phase 5.8a per-milestone diagnostic emission + path scheme — unchanged. Split-IDs flow through cleanly (Phase 5.8a uses `milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json`; the `<id>` after split is whichever post-split id the milestone has).

## Actual API surface shipped

Module `agent_team_v15.milestone_manager` (extensions):

* `MILESTONE_AC_CAP_DEFAULT: int = 10` — locked default cap (matches §L.2 AC1).
* `MAX_SPLIT_HALVES: int = 26` — single-letter alphabet limit. Splitter rejects input that would emit > 26 chunks BEFORE any file mutation.
* `_PHASE_5_9_SPLIT_ARCHIVE_DIR = "_phase_5_9_split_source"` and `_PHASE_5_9_SPLIT_ARCHIVE_FILE = "REQUIREMENTS.original.md"` — non-canonical archive scheme. Directory-scanner consumers (`_list_milestone_ids` filter `(d / "REQUIREMENTS.md").is_file()`; `aggregate_milestone_convergence` and `get_cross_milestone_wiring` iterate `_list_milestone_ids()`; `stack_contract._collect_requirements_texts` globs `*/REQUIREMENTS.md` single-level) all skip the archive automatically (different filename + deeper path).
* `validate_plan(milestones, *, ac_cap=None) -> PlanValidationResult` — extended with cap kwarg. `ac_cap=None` reads `MILESTONE_AC_CAP_DEFAULT`; `ac_cap=0` disables the gate (legacy `>13` warn floor still fires); `ac_cap >= 3` is the active gate. The cap-gate produces ERRORS (not warnings) per §L.
* `split_oversized_milestones(milestones, *, cap, cwd=None) -> list[MasterPlanMilestone]` — main entry. Pre-mutation 26-half guard. Returns input list unchanged when no milestone exceeds cap (byte-identical for `<= cap` plans — backward-compat AC4). When `cwd` is provided, archives the original `REQUIREMENTS.md` and writes per-half active checklists.

Module `agent_team_v15.config` (extensions):

* `V18Config.milestone_ac_cap: int = 10`.
* `_validate_v18_phase59(cfg: V18Config) -> None` — rejects `< 0` and `1`/`2`; allows `0` and `>= 3`.

CLI:

* `--milestone-ac-cap N` argparse flag at the canonical site adjacent to `--cumulative-wedge-cap`.

## Risks closed

* **R-#43** (M1 has 15 ACs; planner does not auto-split) — CLOSED at the source level. The auto-split helper redistributes any milestone with `> cap` ACs into halves; the validator gates above-cap milestones as a hard error post-split. AC3 live evidence (post-Phase-5.9 M1 has ≤ 10 ACs at HEAD) is the §O.4.15 closeout row, deferred to operator-authorised smoke.

## Split heuristic shipped (algo lock)

```python
def _split_milestone_into_chunks(ac_count: int, cap: int) -> list[int]:
    chunks = []
    remaining = ac_count
    chunk_size = cap - 2  # = 8 when cap=10
    while remaining > cap:
        chunks.append(chunk_size)
        remaining -= chunk_size
    chunks.append(remaining)
    return chunks
```

Locked by `test_split_heuristic_cap_minus_2_chunking` parametrized:

| ac_count | chunks (cap=10) |
|---|---|
| 11 | [8, 3] |
| 12 | [8, 4] (the canonical §L.2 AC2 example) |
| 15 | [8, 7] (M1's empirical 15-AC shape) |
| 18 | [8, 10] (final remainder may equal cap) |
| 19 | [8, 8, 3] (recursion → 3 halves) |
| 21 | [8, 8, 5] |
| 22 | [8, 8, 6] |

The "leave headroom" rationale (chunk smaller than cap) keeps remainders above the `< 3` advisory floor for typical inputs (12 ACs → 8/4, not 10/2).

## Stable-id scheme (locked)

* Pattern: `<id>-a, <id>-b, <id>-c, ...` — flat single-letter alphabet.
* 26-half cap (`MAX_SPLIT_HALVES`) — at cap=10, max ac_count = `(N-1)*(cap-2) + cap = 25*8 + 10 = 210`. Inputs > 210 ACs raise `ValueError` BEFORE any file mutation.
* Multi-letter forms (`-aa`, `-ab`) intentionally rejected via the parser regex `(?![-a-z])` negative lookahead — splitter cannot emit them, parser refuses to round-trip them.
* Nested forms (`-a-b`) intentionally rejected — flat sequence only.

## Stable-id consumer audit (Phase 5.8a lesson #2 — walked every milestone_id keyed surface)

| Consumer | Keying | Split-id outcome |
|---|---|---|
| `STATE.json::milestone_progress[<id>]` | dict key | ✓ initialised per id at start (cli.py `_initialize_plan_state_early`) |
| Phase 4.6 `_anchor/<id>/_complete/` | path embed | ✓ each split-id gets own anchor |
| Phase 5.5 `_anchor/_complete/_quality.json` | sibling of anchor tree | ✓ sibling of split-id anchor |
| Phase 5.5 state-invariants Rule 1 | iterates `milestone_progress.items()` | ✓ scans whatever keys exist |
| Phase 5.4 `audit_fix_rounds` | per-id in progress dict | ✓ per-split-id counter |
| Phase 5.8a `<run-dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json` | path embed | ✓ per-split-id artifact |
| Phase 4.6 `--retry-milestone <id>` | operator-supplied id | ✓ operator passes split-id |
| Phase 4.6 `_prune_anchor_chain(milestone_id)` | per-id chain | ✓ each split-id has own chain |
| Phase 4.3 `wave_ownership` | wave-letter only, NOT id | ✓ no impact |
| Phase 4.7 `wave_boundary` | wave-letter only | ✓ no impact |
| `_milestone_to_json_dict` | no field dropping | ✓ preserves all fields incl. split-id `id` |
| Wave 4.5 cascade reasons | generic strings, no id embed | ✓ no impact |
| `update_milestone_progress` | caller-supplied id | ✓ caller passes split-id |
| `MilestoneManager._list_milestone_ids` | dir-iter + `(d / "REQUIREMENTS.md").is_file()` | ✓ orig source filtered out (canonical REQUIREMENTS.md moved to archive) |
| `aggregate_milestone_convergence` | iterates `_list_milestone_ids()` | ✓ orig source skipped |
| `get_cross_milestone_wiring` | iterates `_list_milestone_ids()` | ✓ orig source skipped |
| `stack_contract._collect_requirements_texts` | single-level glob `*/REQUIREMENTS.md` | ✓ orig source two levels deeper + different filename, both safety nets fire |
| `endpoint_prober._milestone_requirements_path` | per-id direct lookup | ✓ split halves have own REQUIREMENTS.md |
| `dod_feasibility_verifier` | caller-supplied milestone_dir | ✓ caller passes split-half dir |
| `_RE_MILESTONE_HEADER` regex | `\d+(?:-[a-z])?` | ✓ accepts `7-a`; rejects `7-aa` / `7-` |
| `_id_form` regex in `_parse_deps` | identical shape | ✓ deps to split halves round-trip |
| `generate_master_plan_md` heading-num | suffixed-aware regex | ✓ emits parser-compatible `## Milestone 7-a:` |
| `update_master_plan_status` | uses `_RE_MILESTONE_HEADER` for block bounds | ✓ fixed cascadingly via parser regex widen |

## REQUIREMENTS.md scoping contract (Blocker 2 closure)

Original preservation: when split fires for milestone `<orig-id>`:

1. Pre-mutation guard validates input fits within 26 halves.
2. `Path.rename(milestones/<orig-id>/REQUIREMENTS.md, milestones/<orig-id>/_phase_5_9_split_source/REQUIREMENTS.original.md)` — atomic POSIX move within the same parent.
3. Per-half active `REQUIREMENTS.md` written at `milestones/<orig-id>-a/REQUIREMENTS.md`, `<orig-id>-b/REQUIREMENTS.md`, etc. Each contains only the half's AC checkboxes (one `- [ ] AC-XXX (review_cycles: 0)` per assigned AC), plus a `## Notice — Phase 5.9 auto-split` header that points at the archive for context.
4. Idempotency: re-running split with the archive already present raises `FileExistsError`. Re-run is a deliberate operator action.

Why directory scanners skip the orig source: every consumer keys via either `_list_milestone_ids()` (which filters `(d / "REQUIREMENTS.md").is_file()` at `milestone_manager.py:1430-1434`) OR via single-level glob `*/REQUIREMENTS.md` (`stack_contract.py:946`). After the move, `<orig-id>/REQUIREMENTS.md` no longer exists at the canonical path; only `<orig-id>/_phase_5_9_split_source/REQUIREMENTS.original.md` remains, which fails BOTH the canonical-path check AND the single-level glob (path is two segments deep AND filename differs). Locked by `test_original_split_source_excluded_from_list_milestone_ids` + `test_aggregate_convergence_ignores_original_unsplit_requirements` + `test_cross_milestone_wiring_ignores_original_unsplit_requirements` + `test_stack_contract_glob_skips_archived_original`.

## Validator gate semantics (Blocker 4 corrected)

| Mode | Cap | Behaviour |
|---|---|---|
| Default | `MILESTONE_AC_CAP_DEFAULT = 10` | `> 10` ACs → ERROR; `< 3` ACs → WARNING (advisory); 0 ACs (foundation) → exempt |
| Operator `ac_cap=0` | (disabled) | gate disabled; legacy pre-Phase-5.9 `> 13` ACs WARNING floor restored; auto-split helper also a no-op |
| Operator `ac_cap=N >= 3` | N | `> N` ACs → ERROR; `< 3` ACs → WARNING |

The cap-gate runs against the post-auto-split shape (auto-split runs upstream of `validate_plan` in cli.py). A properly split plan never trips the gate. Locked by `test_validate_plan_errors_directly_on_above_cap_input` + `test_split_then_validate_passes_for_above_cap_input` + `test_validate_plan_ac_cap_zero_disables_gate` + `test_validate_plan_ac_cap_default_falls_back_to_module_constant` + `test_validate_plan_under_3_acs_still_warns_post_phase_5_9` + `test_validate_plan_foundation_zero_acs_exempt_from_gate` + `test_validate_plan_at_cap_passes`.

## Operator override + config validation

`--milestone-ac-cap N` argparse flag mirrors Phase 5.4 `--milestone-cost-cap-usd` + Phase 5.7 `--cumulative-wedge-cap`:

* Default `None` → falls through to `config.v18.milestone_ac_cap` (default 10).
* `0` → disables both split AND gate (legacy unbounded; preserves pre-Phase-5.9 behaviour byte-identical except for the planner-prompt edit).
* `1` / `2` → rejected at CLI parse time (matches the config validator).
* Negative → rejected.
* `>= 3` → active cap.
* CLI override threading via `getattr(args, "milestone_ac_cap", None)` (legacy-Namespace robust per Phase 5.4 / 5.7 pattern).

Locked by `test_milestone_ac_cap_default_constant_is_10` + `test_max_split_halves_is_26` + `test_config_validator_rejects_cap_1_and_2` + `test_config_validator_rejects_negative_cap` + `test_config_validator_accepts_cap_zero_and_above_3`.

## Tests shipped (48 fixtures in tests/test_pipeline_upgrade_phase5_9.py)

* Blocker 1 — parser/generator/status-updater suffix support (5 fixtures): parse round-trip with suffixed IDs, regen MD with suffixed IDs, status update on suffixed IDs, legacy numeric-only headers unchanged, double-letter rejection.
* Splitter heuristic (parametrized 7 fixtures): 11/12/15/18/19/21/22-AC inputs.
* Backward-compat (3 fixtures): no-op when all `<= cap`; 30-AC across 6 milestones; foundation 0-AC exempt.
* AC ordering + titles (2 fixtures): cumulative AC ordering preserved; `(Part N)` title suffixes.
* Dependency rewrite (3 fixtures): within-split chain (`b deps a`); 3-way chain (`b deps a, c deps b`); downstream rewrite to last half.
* 26-half guard (3 fixtures): at-max (210 ACs) succeeds; over-max (211, 300 ACs) raises; pre-mutation discipline holds (no file mutation on guard fail).
* REQUIREMENTS.md scoping + archive (4 fixtures): per-half checkboxes, atomic archive, idempotency, `check_milestone_health` per-half.
* Scanner-skip (4 fixtures): `_list_milestone_ids` excludes orig; aggregate convergence skips; cross-milestone wiring skips; stack_contract glob skips.
* Validator (7 fixtures): direct cap error, split-then-validate pass, cap=0 disables, default falls back, `<3` warn preserved, foundation exempt, at-cap passes.
* Constants + config (4 fixtures): default-10 lock, max-26 lock, validator rejects 1/2/negative, accepts 0/>=3.
* Persistence (1 fixture): post-split JSON + MD round-trip.
* Constants smoke + miscellaneous (2 fixtures): split persists post-split master_plan; pre-mutation file-untouched guard.
* Reviewer-correction locks (3 fixtures, `34bab7a`): re-split-of-half rejection, 26-half flat-letter invariant, multi-original archive preflight.

## Phase 5.7 + 5.6 + 5.5 + 5.4 + 5.3 + 5.2 + 5.1 + 5.8a + 4.x contract preservation evidence

* **Phase 5.7 (bootstrap watchdog).** Splitter is in-process Python; not SDK-dispatched. `_invoke_*_with_watchdog` family + `_cumulative_wedge_budget` + bootstrap respawn + productive-tool-idle watchdog UNTOUCHED. Phase 5.9's auto-split runs synchronously in the cli planning phase BEFORE any wave dispatch.
* **Phase 5.6 (unified build gate).** `WaveBVerifyResult` / `WaveDVerifyResult` UNTOUCHED. `unified_build_gate.run_compile_profile_sync` UNTOUCHED. The cap is enforced at PLAN VALIDATION time, far upstream of the build gate.
* **Phase 5.5 (Quality Contract).** `_evaluate_quality_contract`, `_finalize_milestone_with_quality_contract`, `_quality.json` sidecar, `confirmation_status`, layer-2 invariants, §M.M13 suppression registry — all UNTOUCHED. Split-IDs flow through `update_milestone_progress` → `milestone_progress[<split-id>]` → resolver naturally; Rule 1's iteration over `milestone_progress.items()` sees split-IDs as just additional dict keys.
* **Phase 5.4 (cycle-1 dispatch + cost cap).** UNTOUCHED. `_run_audit_fix_unified` per-milestone counter increments work on whatever split-ID is current.
* **Phase 5.{1,2,3} (audit termination + path drift + STATE.json quality-debt fields).** UNTOUCHED.
* **Phase 5.8a (cross-package diagnostic).** `cross_package_diagnostic.compute_divergences` + `_emit_phase_5_8a_diagnostic` + `audit_prompts.py` advisory exception UNTOUCHED. The diagnostic artifact path `<run-dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json` uses whatever post-split id the milestone has — natural composition.
* **Phase 4.3 (owner_wave).** Wave attribution by file path, NOT milestone-id. Untouched.
* **Phase 4.5 / 4.6 / 4.7 (cascade lift, anchor capture, wave-boundary block).** Anchor-on-complete writes to `_anchor/<id>/_complete/` — uses whatever id the milestone has. Phase 4.6 `_prune_anchor_chain(milestone_id)` operates per-id; each split-half has own chain. UNTOUCHED.
* **Phase 1 (anchor primitive).** UNTOUCHED.
* **Phase 2 (test-surface lock).** UNTOUCHED.
* **Phase 3 / 3.5 (PreToolUse hook + ship-block).** UNTOUCHED.

## Verification gates passed

* **Targeted slice (§0.5 + Phase 5.{1,2,3,4,5,6,7,8a,9} fixtures):** **1046 passed** at HEAD post-Phase-5.9 (`34bab7a`). 998 baseline + 48 new Phase 5.9 fixtures. 0 regressions across any prior phase. (Initial `229678d` landing was 1043; +3 from reviewer-correction locks.)
* **Wide-net sweep (§0.6):** **2294 passed**, 3 skipped, **4 pre-existing failures** matching plan §0.1.7 verbatim, 0 regressions vs Phase 5.8a baseline 2246 → +48 from new Phase 5.9 fixtures landing in the wide-net `-k` filter. (Initial `229678d` landing was 2291; +3 from reviewer-correction locks.) Pre-existing failures verbatim:
  * `test_cli.py::TestMain::test_interview_doc_scope_detected`
  * `test_cli.py::TestMain::test_complex_scope_forces_exhaustive`
  * `test_h3e_wave_redispatch.py::test_scaffold_port_failure_redispatches_back_to_wave_a_once`
  * `test_v18_phase4_throughput.py::test_run_prd_milestones_uses_git_isolation_path_even_when_parallel_limit_is_one`
* **Module import smoke (§0.7):** clean — `cli`, `audit_team`, `audit_models`, `fix_executor`, `wave_executor`, `state`, `agent_teams_backend`, `config`, `quality_contract`, `state_invariants`, `unified_build_gate`, `cross_package_diagnostic`, `milestone_manager`, `agents` all import without warnings.
* **Backward-compat fixture spot-check:** Phase 1.6 / 4.{1-7} / 5.{1-8a} all green byte-identical at HEAD post-Phase-5.9. Three test files updated to track Phase 5.9's new contract:
  * `tests/test_v18_vertical_slice_fixes.py::TestValidatePlan::test_warns_on_oversized_milestone` — updated to assert both new error path AND legacy preserve path.
  * `tests/test_v18_vertical_slice_fixes.py::TestPlannerPrompt::test_prompt_has_sizing_rules` — updated to `Maximum: 10 ACs per milestone`.
  * `tests/test_agents.py::TestPhaseStructuredPlanning::test_milestone_sizing_instruction` — same prompt assertion update.
* **mcp__sequential-thinking + context7:** sequential-thinking used for the consumer-map walk (Phase 5.8a lesson #2) and the cap-2 chunking algo lock-in. context7 not needed in practice — design surface lined up with existing Phase 4.x + 5.4 + 5.7 patterns.

## Smoke evidence (when applicable)

NOT applicable to the Phase 5.9 source landing. Per dispatch direction:

* **AC3 live smoke** (post-Phase-5.9 M1 has ≤ 10 ACs at HEAD; expected M1 split shape: `milestone-1-a` (8 ACs) + `milestone-1-b` (7 ACs) per 15→8/7 heuristic) — operator-authorised separate activity (cost ~$30-60).
* **6-milestone synthetic smoke** (AC1 backward-compat: 30-AC PRD across 6 milestones produces no auto-split) — operator-authorised separate activity (cost ~$30-60 if it runs as a live build).

Both smokes are §O.4.15 / §O.4.16 closeout-evidence rows; deferred to operator-authorised follow-up. Source-level contracts are locked at the unit-fixture level so the eventual smoke batch consumes the same shape.

## Open follow-ups (not blocking)

* **Phase 5.9 live M1+M2 smoke** — operator-authorised. AC3 evidence row §O.4.15.
* **Phase 5.9 6-milestone synthetic smoke** — operator-authorised. §O.4.16.
* **Phase 5.8a smoke batch authorisation** — operator-authorised sequential M1+M2 diagnostic smokes; §K.2 decision-gate evaluator session reads per-milestone diagnostics.
* **Phase 5.7 closeout-smoke rows O.4.5–O.4.11** — Phase 5.7 carry-over.
* **§M.M11 calibration smoke for Phase 5.6** — Phase 5.6 carry-over.
* **`_run_wave_compile` shim removal** — Phase 5.6 carry-over.
* **`--legacy-permissive-audit` removal** — Phase 5.5 carry-over (evidence-gated per §M.M15).
* **`test_walker_sweep_complete.py` line-pinned lint failures** — pre-existing (per Phase 5.5 landing memo). Out of Phase 5.9 scope.

## Out-of-scope items the plan flags but Phase 5.9 did NOT touch

* PRD decomposition strategy beyond the AC-count cap (per §N).
* `vertical_slice` planner_mode (preserved per §N).
* Multi-stack-profile support (Phase 6+).
* Per-role model routing (Phase 6+).
* Operator-review checkpoints for DEGRADED milestones (Phase 6+).
* AUDIT_REPORT.json schema — unchanged.
* Quality Contract gate filters — unchanged.
* `cascade_quality_gate_blocks_complete` at audit_team.py:161 — UNCHANGED.
* `_anchor/_complete/` directory name — UNCHANGED (§M.M16).
* `audit_fix_rounds` field name — UNCHANGED (§M.M16).
* `score_healthy_threshold` default 90 — UNCHANGED (§M.M16).

## Surprises

1. **Three additional plumbing surfaces needed updating beyond `_RE_MILESTONE_HEADER`.** Initial scope check-in identified the parser regex + generator heading-num + status-updater (transitive). Investigation surfaced TWO more: (a) `_id_form` regex inside `_parse_deps` rejects `milestone-7-a` as "non-ID dependency token" (drops the dep with a `WARNING` log), so dependency edges from split halves were silently lost in plan parsing — fix was the same regex shape `^milestone-\d+(?:-[a-z])?$`; (b) the parser regex needed a `(?![-a-z])` negative lookahead to actually reject `7-aa` and `7-` shapes (the optional `-[a-z]?` would otherwise greedy-then-backtrack to capture only the digits, leaving the rest as title prose, producing a malformed milestone with id from the `- ID:` line override). The parser/dep-parser/generator triple now share one shape end-to-end.
2. **`test_walker_sweep_complete.py` is line-pinned and pre-existing-broken.** Phase 5.5 landing memo flagged this. Phase 5.9 added ~30 lines to milestone_manager.py + ~25 lines to cli.py + ~15 lines to config.py; line drift compounds but the actual lint contract (no NEW unsafe walkers introduced) is preserved. Phase 6+ cleanup will need to refresh the allow-list line numbers.
3. **`MasterPlanMilestone` has no `_coerce_*`-style silent drops.** Phase 5.8a's reviewer correction #5 caught a similar gap on `ContractResult`. Audited `_milestone_to_json_dict` (`milestone_manager.py:353-375`); enumerates every field via `getattr` with defaults — no field drops the new `id` shape. No analogous coercer found elsewhere for `MasterPlanMilestone`.
4. **`<orig-id>/` directory is a "ghost dir" post-split** (intentionally). It contains only `_phase_5_9_split_source/REQUIREMENTS.original.md` after the move; the canonical-`REQUIREMENTS.md` filter at `_list_milestone_ids` is the single gate that excludes it from active milestone discovery. Other files in `<orig-id>/` (TASKS.md, AGENT_LOGS, ...) — if any — are NOT moved (per operator approval). Sweeping more risks unforeseen consumers; the `_list_milestone_ids` filter is sufficient.
5. **The `(Part N)` title suffix is human-readable, not machine-parsed.** No code reads the title for routing decisions; it's purely operator UX. Operators see `## Milestone 7-a: Invoice Creation (Part 1)` in MASTER_PLAN.md and `[Phase 5.9 §L: auto-split applied (cap=10); 4 milestone(s) post-split.]` in BUILD_LOG.

---

**Phase 5.9 closes the v5 Phase 5 plan at the source level.** All 9 sub-phases (5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8a, 5.9) are shipped. Final closeout still requires the operator-authorised smoke evidence per §O.4.15 / §O.4.16 (Phase 5.9) + §O.4.14 (Phase 5.8a §K.2 decision gate) + §O.4.5-§O.4.11 (Phase 5.7) + Phase 5.6 §M.M11 calibration smoke.

## Note for Phase 6+ (when the plan is authored)

Phase 5.9 ships the structural primitive. Forward-compatible extensions:

* **Multi-letter suffix (`-aa`, `-ab`)**: would require widening `_RE_MILESTONE_HEADER` regex AND `_id_form` AND `generate_master_plan_md` heading-num shape AND the splitter's `_suffix_for_half_index` arithmetic AND raising `MAX_SPLIT_HALVES`. Not on the critical path for Phase 6 unless milestones with > 210 ACs become realistic.
* **Per-half AC text in split REQUIREMENTS.md**: Phase 5.9 emits one `- [ ] AC-XXX (review_cycles: 0)` checkbox per assigned AC. Future enhancement could pull AC text from the IR (`product_ir.acceptance_criteria[]`) and render `- [ ] AC-XXX — <text> (review_cycles: 0)`. Out of Phase 5.9 scope; the orchestrator agent reads the archived original for full prose.
* **Operator-driven `--retry-milestone <orig-id>`**: today operators must pass split-half IDs (`milestone-7-b`). Phase 6+ could accept the orig-id and resolve to the latest half automatically. Not blocking.

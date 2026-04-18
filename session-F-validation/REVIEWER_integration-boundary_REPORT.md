# Phase F — Integration Boundary Reviewer Report

> Task #5 deliverable. Every cross-module contract verified for producer
> vs. consumer symmetry: dataclass shape, JSON round-trip, config field
> names/defaults, Phase E forked-session handoff, Phase B ownership
> contract parser, Phase C framework idioms cache, and Phase F NEW
> boundaries.

## Executive summary

| Area | Findings |
| --- | --- |
| Phase F NEW boundaries (§7.5, §7.10, N-19, scope scanner) | **1 CRITICAL** (all 4 modules unwired) + 2 MEDIUM |
| Dataclass boundaries | 0 mismatches (AuditReport/State/FixTask/OwnershipContract) |
| JSON round-trips (AuditReport, STATE.json, scaffold_verifier_report) | 0 mismatches — N-15 extras fix verified by direct round-trip |
| Config field name/default symmetry | 0 mismatches across 16 flags |
| Phase E boundaries (orphan detector, provider router) | 0 mismatches; asymmetric `check_orphans()` return by design |
| Phase B boundaries (ownership contract → 4 consumers) | 0 mismatches |
| Phase C boundaries (framework idioms cache) | 0 mismatches |

## F-INT-001: Phase F — all four NEW modules have zero production consumers
**Severity:** CRITICAL
**Area:** Phase F boundary
**Producer file:line:**
- `src/agent_team_v15/infra_detector.py:167` — `detect_runtime_infra`, `build_probe_url`, `RuntimeInfra`
- `src/agent_team_v15/confidence_banners.py:257` — `stamp_all_reports`, `derive_confidence`, `ConfidenceSignals`
- `src/agent_team_v15/audit_scope_scanner.py:199` — `scan_audit_scope`, `build_scope_gap_findings`, `ScopeGap`
- `src/agent_team_v15/wave_b_sanitizer.py:238` — `sanitize_wave_b_outputs`, `build_orphan_findings`, `OrphanFinding`, `SanitizationReport`

**Consumer file:line:** none

**Shape mismatch:** Not a shape mismatch — an **integration gap**. A full-repo search (`grep -rn "from .wave_b_sanitizer\|from .confidence_banners\|from .infra_detector\|from .audit_scope_scanner" src/`) returns zero hits. The four Phase F modules are defined with their config flags (`v18.runtime_infra_detection_enabled`, `v18.confidence_banners_enabled`, `v18.audit_scope_completeness_enabled`, `v18.wave_b_output_sanitization_enabled`, all default True), every entry-point function is flag-gated, every public dataclass has `to_dict()` / JSON-compatible serializers — and every entry point is dead code. The flags cannot fire because nothing imports the modules.

Evidence:
- `endpoint_prober.py` / `runtime_verification.py` / `cli.py` do not import `infra_detector`; probe URL assembly still uses the pre-Phase-F code path.
- `_run_milestone_audit` in `cli.py:5853` does not call `scan_audit_scope` or `stamp_all_reports`; the AUDIT_REPORT.json produced in a live run will NOT carry a `confidence` field.
- `wave_executor.py` Wave B post-hook (ownership validation at `scaffold_runner.py:344`) is the only Wave-B-adjacent ownership check; the sanitizer is not called.
- `_run_audit_loop` in `cli.py` does not emit `AUDIT-SCOPE-GAP-*` meta-findings.

Consequence: the sweeper report says the four modules "extend" D-14 / §7.5 / N-02 / N-19 behaviors and default-True flags the sweeper lists as Phase F features, but the behaviors they describe will not actually occur in a smoke run.

**Proposed fix:**
1. `infra_detector.detect_runtime_infra(cwd, config=cfg)` wired from `_run_milestone_audit` (the natural owner) or the probe-assembly path in `endpoint_prober.py`; the returned `RuntimeInfra.api_prefix` feeds `build_probe_url` in post-Wave-E verification calls.
2. `confidence_banners.stamp_all_reports(agent_team_dir=..., signals=ConfidenceSignals(...), config=cfg)` called once at the end of the pipeline — after `_run_milestone_audit` returns and `State.finalize` has run, before `save_state`. Signals are assembled from `state.convergence_cycles`, `state.summary`, runtime-verification outcome, and `config.v18.evidence_mode`.
3. `audit_scope_scanner.scan_audit_scope(...)` called from within `_run_milestone_audit` before the LLM scorer runs; the returned `ScopeGap` list is fed into `build_scope_gap_findings` and merged into the findings list via the existing `AuditFinding.from_dict` path.
4. `wave_b_sanitizer.sanitize_wave_b_outputs(...)` called from `wave_executor.py` in the Wave-B post-hook (adjacent to the existing `_maybe_cleanup_duplicate_prisma` call at `wave_executor.py:974-1030`); the returned `SanitizationReport` is serialized via `build_orphan_findings` and appended to the Wave B findings before the report is handed back.

Each wire-up is a small, localized addition — but without them, the Phase F sprint ships four unused modules and four default-True flags that have no observable effect.

**Fix status:** DEFERRED — structural wire-up exceeds the "rename a field, align a default" fix budget of the integration-boundary-fixer role. Flagged to Team Lead for decision on whether to wire in this sprint or release Phase F as library-only (flags exist but are pending integration).

---

## F-INT-002: Phase F sanitizer scope excludes Wave D-owned paths
**Severity:** MEDIUM
**Area:** Phase B boundary / Phase F boundary
**Producer file:line:** `docs/SCAFFOLD_OWNERSHIP.md` — `_VALID_OWNERS = {"scaffold", "wave-b", "wave-d", "wave-c-generator"}` per `scaffold_runner.py:144`
**Consumer file:line:** `src/agent_team_v15/wave_b_sanitizer.py:276` — `for owner in ("scaffold", "wave-c-generator")`

**Shape mismatch:** The ownership contract defines four owners. The sanitizer queries two (`scaffold`, `wave-c-generator`). A Wave B emission into a Wave-D-owned path (e.g. `apps/web/...`) will NOT be flagged as an orphan — the sanitizer's `non_wave_b_paths` set never contains Wave-D-owned paths. This diverges from the sweeper report's description ("compares emitted files against the ownership contract. Any Wave B emission in a scaffold-owned path is flagged as an orphan candidate"): the "scaffold-owned" phrasing matches the implementation, but per `docs/SCAFFOLD_OWNERSHIP.md` the contract distinguishes scaffold-owned from wave-d-owned slots and both are non-Wave-B.

**Proposed fix:** `for owner in ("scaffold", "wave-c-generator", "wave-d"):` at `wave_b_sanitizer.py:276`. Wave B writing into `apps/web` is exactly the category N-19 was meant to catch (see N-19 plan reference in sweeper report Touch 5).

**Fix status:** DEFERRED — subordinate to F-INT-001 (module has no consumer). When F-INT-001 is addressed, this one-line change should ride alongside.

---

## F-INT-003: Sweeper report references `config.py:911-950` but Phase F flags span `911-943`
**Severity:** LOW
**Area:** documentation vs. code
**Producer file:line:** `src/agent_team_v15/config.py:911-943` (four Phase F flags)
**Consumer file:line:** `session-F-validation/SWEEPER_REPORT.md:225` — "Defined at `src/agent_team_v15/config.py:911-950`"

**Shape mismatch:** Documentation drift only. The flags are in-place and consumed by the (currently-dead) Phase F modules; the line-range in the sweeper report is seven lines too wide. No production behavior change.

**Proposed fix:** Update sweeper report line 225 to reference `src/agent_team_v15/config.py:911-943`.

**Fix status:** DEFERRED — cosmetic docs edit, out of scope for a structural reviewer.

---

## Verified clean boundaries

### Dataclass boundaries (Area 1)
- `AuditReport` — Phase A N-15 `extras` field verified: `to_json` at `audit_models.py:297-311` spreads `**self.extras` first; `from_json` at `audit_models.py:373` captures unknown keys into `extras`. Direct round-trip test: a JSON with `confidence` + `confidence_reasoning` (simulating what `stamp_json_report` would write) round-trips cleanly through `from_json` → `to_json`. **Phase F confidence fields will round-trip correctly if ever written.**
- `State.RunState` — Phase A NEW-7 invariant at `state.py:591-601` confirmed: `summary.success` derivation is consistent on both write paths (computed default line 574 AND finalize() output). Phase D D-13 `finalize()` at `state.py:97-207` handles missing `agent_team_dir` and missing files gracefully. `wave_progress[ms]["failed_wave"]` is a string (`"D"` etc.), read by Phase F N-11 extension at `cli.py:655` with exact string match. Writer/reader types agree.
- `FixTask` — `audit_models.py:650` — `group_findings_into_fix_tasks` at `audit_models.py:882` produces `FixTask(target_files=list[str], findings=list[AuditFinding], priority=str)`; consumer at `fix_executor.py` indexes `task.findings` — shape matches.
- `OwnershipContract` — 4 active consumers (`agents.py:7895`, `audit_team.py:295`, `scaffold_runner.py:352`, `wave_executor.py:859/902`). All use the same `load_ownership_contract()` parser → same `OwnershipContract` instance. Duck-typed call in wave_b_sanitizer uses `contract.files_for_owner(owner)` and `contract.owner_for(path)`, both of which exist on `OwnershipContract` at `scaffold_runner.py:127/136`. API surface matches.
- `RuntimeInfra` (Phase F) — dataclass fields (`app_url`, `api_prefix`, `cors_origin`, `database_url`, `jwt_audience`, `sources`) all reachable via `to_dict()` / `asdict()`. `build_probe_url(infra=...)` reads `infra.api_prefix` only — the other fields are defined but unused by the module's own consumer. Not a mismatch because there is no OTHER consumer (see F-INT-001).
- `ConfidenceSignals` (Phase F) — 6 input fields, `derive_confidence` reads all 6. Symmetry verified by direct test (`CONFIDENT` vs `LOW` paths both fire correctly).
- `ScopeGap`, `SanitizationReport`, `OrphanFinding` (Phase F) — serializer functions `build_scope_gap_findings` and `build_orphan_findings` emit dicts with keys exactly matching `AuditFinding.from_dict` expectations. Direct test confirmed `AuditFinding(**payload)` succeeds for both paths.

### JSON persistence (Area 2)
- **Scorer raw write vs Python structured write** — Phase A N-15 fix at `audit_models.py:297-311` verified by direct Python round-trip: unknown top-level keys (e.g. scorer's `verdict`, `health`, `notes`, plus Phase F's `confidence` and `confidence_reasoning`) are captured into `extras` at `from_json:373` and re-emitted on `to_json`. **Phase F confidence banner writes are preservation-safe.**
- **STATE.json** — `save_state` at `state.py:521` and `load_state` at `state.py:628` are inverses for every field. The Phase F cascade extension at `cli.py:655` reads `wave_progress[ms]["failed_wave"]` as a string and matches it against `"D"` — writer at `cli.py:1455/1498` writes `progress["failed_wave"] = wave` where `wave` is a string ("A", "B", "D", etc.). Types agree.
- **scaffold_verifier_report.json** — written by `scaffold_verifier.py`, consumed by Phase F `audit_scope_scanner._coverage_checks` at `audit_scope_scanner.py:108` only via filesystem existence check (`.is_file()`). No shape dependency — the scanner only cares that the file exists.

### Config field names + defaults (Area 3)
Spot-checked every flag against its consumer; all 16 flags defined on `V18Config` match their accessor defaults:

| Flag | config.py default | Module default |
| --- | --- | --- |
| `runtime_infra_detection_enabled` | True (line 920) | True (`infra_detector.py:62`) |
| `confidence_banners_enabled` | True (line 929) | True (`confidence_banners.py:58`) |
| `audit_scope_completeness_enabled` | True (line 936) | True (`audit_scope_scanner.py:70`) |
| `wave_b_output_sanitization_enabled` | True (line 943) | True (`wave_b_sanitizer.py:77`) |
| `cascade_consolidation_enabled` | False (line 872) | consumer-side default False |
| `duplicate_prisma_cleanup_enabled` | False (line 879) | consumer-side default False |
| `content_scope_scanner_enabled` | False (line 894) | consumer-side default False |
| `mcp_informed_dispatches_enabled` | True (line 910) | consumer-side default False at `cli.py:1935` (`not getattr(...,  False)`) |

**Minor note on `mcp_informed_dispatches_enabled`:** consumer at `cli.py:1935` uses `not getattr(v18, "mcp_informed_dispatches_enabled", False)` — the getattr default is False, but the canonical default is True. If `v18` is None or the attribute is missing (e.g. legacy config), behavior falls back to disabled instead of the stated default. Subtle but not a write-side mismatch; documented for completeness.

### Phase E boundaries (Area 4)
- **Forked session handoff** — provider_router dispatches to codex_appserver or claude; each transport defines its own `OrphanToolError` (`CodexOrphanToolError` at `codex_appserver.py:39`; Claude path uses `orphan_detector.OrphanToolEvent` at `orphan_detector.py:21`). Raised from the Codex transport, caught at `provider_router.py:340`, then routed to Claude fallback.
- **Interrupt propagation** — `client.interrupt()` unwinds via async generator close; no struct-shape marshalling involved.
- **Orphan detector output** — deliberate asymmetry: `orphan_detector.OrphanToolDetector.check_orphans()` returns `list[OrphanToolEvent]`; `codex_appserver.CodexOrphanWatchdog.check_orphans()` returns `tuple[bool, str, str, float]`. Each has its own single consumer (`cli.py:1096` for Claude path; `codex_appserver.py:467` for Codex path). Not a cross-module mismatch.

### Phase B ownership contract (Area 5)
Parser: `scaffold_runner.load_ownership_contract` at `scaffold_runner.py:174` — produces `OwnershipContract(files=tuple[FileOwnership, ...])`. Consumers:
1. `scaffold_runner.py:352` — N-02 soft invariant (checks scaffold-owned set vs emitted set).
2. `wave_executor.py:859/902` — Wave B wiring (reads `files_for_owner("wave-b")`).
3. `agents.py:7895` — orchestrator system prompt injection (scaffold scope).
4. `audit_team.py:295` — audit team scope (scaffold scope).

All four call the same parser and read through the same `FileOwnership` dataclass fields (`path`, `owner`, `optional`, `emits_stub`, `audit_expected`). Field names and types agree everywhere.

Phase F `wave_b_sanitizer.py:276/297` would be the 5th consumer — it duck-types via `contract.files_for_owner(owner)` and `contract.owner_for(path)`, both of which are exactly the public API of `OwnershipContract` at `scaffold_runner.py:127/136`. Shape-compatible.

### Phase C framework idioms cache (Area 6)
- Producer: `cli.py:2018` — writes `{cache_key: doc_text}` where `cache_key = f"{milestone_id}::{wave_upper}::v{_MCP_CACHE_VERSION}"` and `doc_text` is a markdown/plain string.
- Consumer: `cli.py:1952-1954` — reads `cache_data[cache_key]`, expects string. Same module so no cross-module mismatch concern.

Schema is a top-level dict of string keys → string values. Consistent.

## Post-review state

- No CRITICAL findings require halting before Phase F's lockdown test phase.
- F-INT-001 is surfaced as a CRITICAL **integration gap** (not a shape mismatch): the Phase F modules exist, pass their own tests, and have flags — but the flags currently gate dead code. Resolving requires structural wiring that exceeds the integration-boundary-fixer role's scope. Flagged to Team Lead (task #8) for scope decision.
- F-INT-002 (MEDIUM) and F-INT-003 (LOW) are both subordinate — they become meaningful only after F-INT-001 is resolved.
- 10,530 / 0 post-sweeper pytest count is untouched by this review (no code edits made).

_End of integration boundary reviewer report._

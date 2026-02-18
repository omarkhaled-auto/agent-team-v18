# Phase 1C: Integration + Security + Build 3 Contract Audit

**Auditor:** interface-auditor
**Date:** 2026-02-17
**Source:** `agent-team-v15/src/agent_team/`
**PRDs:** BUILD2_PRD.md, BUILD3_PRD.md, BUILD1_PRD.md

---

## 1. Integration Requirements (INT-001 through INT-020)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| INT-001 | Contract Engine MCP unavailable -> graceful fallback to static scanning | PASS | `cli.py:4413-4449`: tries `create_contract_engine_session()`, on any Exception falls back to loading from local cache file (`contract_cache.json`). ImportError also handled gracefully. |
| INT-002 | Codebase Intelligence MCP unavailable -> fallback to static `generate_codebase_map()` | PASS | `cli.py:4356-4401`: tries MCP-backed `generate_codebase_map_from_mcp()` inside try/except, on failure prints warning and falls back to static `generate_codebase_map()` at line 4387. |
| INT-003 | ArchitectClient exists wrapping 4 tools with try/except | PASS | `mcp_clients.py:177-264`: `ArchitectClient` class wraps `decompose`, `get_service_map`, `get_contracts_for_service`, `get_domain_model`. Each method has `except Exception as exc:` returning safe empty defaults (`{}` or `[]`). |
| INT-004 | `validate_endpoint()` response matches schema | PASS | `contract_client.py:240-278`: returns `ContractValidation` dataclass with `valid: bool`, `violations: list`, `error: str`. Always returns a value (never raises). |
| INT-005 | `register_artifact()` has no retry on slow response (just timeout) | FAIL | `codebase_client.py:275`: uses `_call_with_retry()` from contract_client.py which retries 3 times on transient errors (`OSError`, `TimeoutError`, `ConnectionError`) with exponential backoff. This contradicts the "no retry" requirement. |
| INT-006 | New configs default to `enabled: False` | PASS | `config.py:448` (`AgentTeamsConfig.enabled=False`), `config.py:469` (`ContractEngineConfig.enabled=False`), `config.py:488` (`CodebaseIntelligenceConfig.enabled=False`). All Build 2 features opt-in. |
| INT-007 | `_dict_to_config()` returns `tuple[AgentTeamConfig, set[str]]` -- NOT changed | PASS | `config.py:944`: signature is `def _dict_to_config(data: dict[str, Any]) -> tuple[AgentTeamConfig, set[str]]:`. Returns `(cfg, user_overrides)` at line 1493. `load_config()` at line 1499 also returns `tuple[AgentTeamConfig, set[str]]`. |
| INT-008 | CONTRACT violations use existing Violation dataclass | PARTIAL | `contract_scanner.py:73-81`: defines its OWN `Violation` dataclass (mirrors `quality_checks.Violation` but is a separate class). Comment on line 70 says "mirrors quality_checks.Violation". Same fields, but not the same class -- could cause `isinstance()` confusion. |
| INT-009 | Agent Teams optional -- every feature has CLIBackend fallback | PASS | `agent_teams_backend.py:720-809`: `create_execution_backend()` has 6 branches, all non-success paths return `CLIBackend(config)`. Branch 1: disabled->CLIBackend. Branch 2: env var missing->CLIBackend. Branch 3: CLI unavailable+fallback->CLIBackend. Branch 4: no fallback->RuntimeError. Branch 5: platform incompatible->CLIBackend. Branch 6: all good->AgentTeamsBackend. |
| INT-010 | Windows compat -- pathlib, Windows process model, shell script degradation | PASS | `state.py` uses `pathlib.Path` throughout. `hooks_manager.py:314-316` has `try: chmod(0o755) except OSError: pass` for Windows. `agent_teams_backend.py:853-862` handles Windows Terminal display mode restrictions. `cli.py:3304` uses `--cwd` with `os.getcwd()`. |
| INT-011 | 15-stage pipeline order preserved | PASS | `cli.py` tracks phases via `completed_phases.append()`: init, interview, constraints, codebase_map, design_extraction, pre_orchestration, orchestration, post_orchestration (includes ~12 sub-scans), e2e_backend, e2e_frontend, e2e_testing, browser_testing, verification, complete. The 15-stage pipeline structure is preserved with Build 2 additions (contract registry loading, contract compliance scan) inserted as sub-phases within post_orchestration. |
| INT-012 | All 13 self-healing fix loops still function | PASS | Fix loops verified in cli.py: mock_data_fix, ui_compliance_fix, api_contract_fix, deployment_integrity_fix, asset_integrity_fix, database_dual_orm_fix, database_default_value_fix, database_relationship_fix, silent_data_loss_fix, endpoint_xref_fix, e2e_backend/frontend_fix, browser_testing_fix, review_recovery. Plus Build 2 adds: contract_compliance_fix. All 13+ loops present with scan-then-fix pattern. |
| INT-013 | CONTRACT scans AFTER existing API contract scan | PASS | `cli.py:5811`: `api_contract_scan` runs first. `cli.py:5860`: Contract Compliance scans run after, at line 5862-5929. Ordering verified. |
| INT-014 | Milestone-based execution preserved | PASS | `MilestoneConfig` at `config.py:273-292` preserved with all fields. `cli.py:934` imports `update_milestone_progress` from state.py. Milestone loop code exists in cli.py with milestone_progress tracking. |
| INT-015 | Every scan/feature config-gated with boolean | PASS | All post-orchestration scans gated: `config.post_orchestration_scans.mock_data_scan` (line 5425), `config.post_orchestration_scans.ui_compliance_scan`, `config.post_orchestration_scans.api_contract_scan`, etc. Contract scans gated at line 5863-5871 with individual booleans. Agent Teams gated by `config.agent_teams.enabled`. |
| INT-016 | Depth gating preserved | PASS | `config.py:588-684`: `apply_depth_quality_gating()` handles all 4 depths. Quick mode disables tech research, quality, all post-orchestration scans, all contract scans, all integrity scans, all database scans, E2E, browser testing. Standard disables PRD reconciliation and CONTRACT-003/004. Thorough/exhaustive enable E2E and bump retries. All Build 2 additions (contract_scans.*) properly gated. |
| INT-017 | Signal handler saves contract report + agent teams status | PASS | `cli.py:3219-3248`: `_handle_interrupt()` on double Ctrl+C saves `agent_teams_active` status (line 3237) and calls `save_state()` (line 3241) which persists `contract_report` and `registered_artifacts` from the RunState fields. |
| INT-018 | Resume from STATE.json includes contract state | PASS | `cli.py:3616-3632`: `_build_resume_context()` includes contract_report data (total, implemented, violations, health) and registered_artifacts in the resume context string. `state.py:308-310`: `load_state()` reads back `contract_report`, `endpoint_test_report`, `registered_artifacts`. |
| INT-019 | ScanScope filtering applies to CONTRACT scans | PASS | `contract_scanner.py:839,855,891`: `run_contract_compliance_scan()` accepts `scope: Any | None = None` and passes it to all 4 sub-scans. Each sub-scan (e.g., `run_endpoint_schema_scan` at line 275) accepts `scope` parameter. `cli.py:5891`: passes `scope=scan_scope` to the scan. |
| INT-020 | `load_config()` tuple return preserved | PASS | `config.py:1496-1535`: `load_config()` signature is `-> tuple[AgentTeamConfig, set[str]]`. Returns `_dict_to_config(raw)` which returns `(cfg, user_overrides)`. |

**INT Summary:** 18 PASS, 1 PARTIAL, 1 FAIL

---

## 2. Security Requirements (SEC-001 through SEC-003)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| SEC-001 | MCP client connections do NOT pass ANTHROPIC_API_KEY in env vars | PASS | Grep of `mcp_clients.py`, `contract_client.py`, `codebase_client.py` for "ANTHROPIC_API_KEY" returns 0 matches. `mcp_clients.py:71-74` (Contract Engine) only passes `DATABASE_PATH`. `mcp_clients.py:132-148` (Codebase Intelligence) only passes `DATABASE_PATH`, `CHROMA_PATH`, `GRAPH_PATH`. No API keys in env dicts. |
| SEC-002 | Hook scripts do NOT contain embedded secrets | PASS | `hooks_manager.py` generates 3 scripts: `teammate-idle-check.sh` (lines 109-123), `quality-gate.sh` (lines 144-176), `track-file-change.sh` (lines 195-210). All scripts use stdin JSON parsing for dynamic values. No hardcoded API keys, passwords, tokens, or secrets in any script template. |
| SEC-003 | `save_local_cache()` strips securitySchemes from OpenAPI specs | PASS | `contracts.py:833-849`: `save_local_cache()` deep-copies each spec, checks for `components.securitySchemes`, and `del`s it before writing. Comment explicitly references SEC-003. |

**SEC Summary:** 3 PASS, 0 FAIL

---

## 3. Build 3 Consumption Contract

### 3A: Builder Subprocess Interface

| Check | Status | Evidence |
|-------|--------|----------|
| `python -m agent_team --cwd {dir}` supported | PASS | `cli.py:3303-3307`: `parser.add_argument("--cwd", default=None, help="Working directory for the project (default: current dir)")` |
| `--depth {level}` supported | PASS | `cli.py:3273-3278`: `parser.add_argument("--depth", choices=["quick", "standard", "thorough", "exhaustive"], default=None)` |
| Depth values: quick, standard, thorough, exhaustive | PASS | All 4 values in choices list. `config.py:550-567` (`DEPTH_AGENT_COUNTS`) has all 4 depth entries. |

**3A Summary:** PASS

### 3B: STATE.json Output Format (MOST CRITICAL)

| Check | Status | Evidence |
|-------|--------|----------|
| RunState.to_dict() includes top-level "summary" key | PASS | `state.py:241-246`: `data["summary"] = { "success": ..., "test_passed": ..., "test_total": ..., "convergence_ratio": ... }` added to the serialized dict. |
| summary.success is bool | PASS | `state.py:242`: `"success": not state.interrupted` -- bool result. |
| summary.test_passed is int | PASS | `state.py:243`: `contract_report.get("implemented", 0)` -- int. |
| summary.test_total is int | PASS | `state.py:244`: `contract_report.get("total_contracts", 0)` -- int. |
| summary.convergence_ratio is float | PASS | `state.py:240`: `convergence = req_checked / req_total if req_total > 0 else 0.0` -- float. |
| total_cost at top level (not nested) | PASS | `state.py:28`: `total_cost: float = 0.0` is a top-level RunState field. `asdict(state)` serializes it at top level. |
| STATE.json written to .agent-team/STATE.json | PASS | `state.py:160`: `_STATE_FILE = "STATE.json"`. `save_state()` writes to `directory / "STATE.json"`. `cli.py:4238` calls `save_state(..., directory=str(Path(cwd) / ".agent-team"))`. |
| **STATE.json exists after successful run** | **CRITICAL FAIL** | `cli.py:6887-6891`: On successful completion, `clear_state()` is called which DELETES STATE.json (`state.py:316-320`: `state_path.unlink(missing_ok=True)`). **Build 3 expects to read STATE.json after Build 2 finishes, but the file is deleted on success.** Build 3 can only read STATE.json if Build 2 was interrupted or failed. |
| **summary.success semantics** | **WARNING** | `state.py:235`: `data["interrupted"] = True` is set **always** before computing summary. `state.py:242`: `"success": not state.interrupted` uses the in-memory field (which may be False for checkpoint saves). This creates a contradiction: JSON has `interrupted: true` but summary may have `success: true`. Semantically confusing for Build 3. |

**3B Summary:** CRITICAL FAIL -- STATE.json is deleted on success. Build 3 cannot consume the output.

### 3C: Config.yaml Format

| Check | Status | Evidence |
|-------|--------|----------|
| `depth` key parseable | PASS | `config.py:975-988`: `_dict_to_config()` handles `depth` section. |
| `milestone.enabled` parseable | PASS | `config.py:1134-1169`: handles `milestone` section including `enabled`. |
| `milestone.health_gate` parseable | PASS | `config.py:1145`: `health_gate=ms.get("health_gate", cfg.milestone.health_gate)`. |
| `e2e_testing.enabled` parseable | PASS | `config.py:1204-1218`: handles `e2e_testing` section. |
| `e2e_testing.backend_api_tests` parseable | PASS | `config.py:1212`: `backend_api_tests=et.get("backend_api_tests", ...)`. |
| `post_orchestration_scans.mock_data_scan` parseable | PASS | `config.py:1299-1318`: handles `post_orchestration_scans`. |
| `post_orchestration_scans.api_contract_scan` parseable | PASS | `config.py:1314`: `api_contract_scan=pos.get("api_contract_scan", ...)`. |
| `_dict_to_config()` can parse all without crashing | PASS | All sections have `.get()` with defaults; no crashes on missing keys. |

**3C Summary:** PASS

### 3D: Fix Loop Interface

| Check | Status | Evidence |
|-------|--------|----------|
| `--depth quick` mode works | PASS | `config.py:614-651`: `apply_depth_quality_gating()` handles quick mode, disabling scans but not crashing. CLI accepts `--depth quick`. |
| STATE.json written in quick mode | CONDITIONAL | STATE.json is written at intermediate checkpoints (e.g., `cli.py:4994` after orchestration). However, on successful completion it is deleted (same 3B issue). |
| total_cost present | PASS | `total_cost` is a top-level field on RunState, always serialized. |

**3D Summary:** CONDITIONAL PASS (blocked by 3B STATE.json deletion issue)

### 3E: ExecutionBackend Protocol

| Check | Status | Evidence |
|-------|--------|----------|
| `create_execution_backend()` importable | PASS | `agent_teams_backend.py:720`: `def create_execution_backend(config: AgentTeamConfig) -> ExecutionBackend:` is a top-level module function. `cli.py:4801-4802` imports and calls it successfully. |
| Returns ExecutionBackend implementor | PASS | Returns either `CLIBackend(config)` or `AgentTeamsBackend(config)`. Both implement `ExecutionBackend` Protocol (`agent_teams_backend.py:92`). |

**3E Summary:** PASS

---

## 4. Findings Summary

### CRITICAL Findings

| ID | Severity | Description | Location |
|----|----------|-------------|----------|
| B3-001 | **CRITICAL** | STATE.json is deleted on successful completion via `clear_state()`. Build 3 expects to read `{output_dir}/.agent-team/STATE.json` after Build 2 finishes, but the file will not exist if the run succeeded. Build 3 can only consume STATE.json from interrupted/failed runs. | `cli.py:6890-6891`, `state.py:316-320` |

### HIGH Findings

| ID | Severity | Description | Location |
|----|----------|-------------|----------|
| B3-002 | HIGH | `summary.success` semantics are contradictory. `save_state()` always sets serialized `interrupted: true` (line 235) but `summary.success = not state.interrupted` uses the in-memory field which may be False. The JSON will say `interrupted: true` and `success: true` simultaneously for checkpoint saves. | `state.py:235,242` |
| INT-005-F | HIGH | `register_artifact()` in `codebase_client.py` uses `_call_with_retry()` which retries 3x on transient errors. PRD requires "no retry on slow response (just timeout)". | `codebase_client.py:275`, `contract_client.py:104-160` |

### LOW Findings

| ID | Severity | Description | Location |
|----|----------|-------------|----------|
| INT-008-W | LOW | `contract_scanner.py` defines its own `Violation` dataclass (line 74) instead of importing from `quality_checks.py`. Same fields but different class. Could cause `isinstance()` issues if code mixes the two. Comment says "mirrors" but does not import. | `contract_scanner.py:70-81` |

---

## 5. Score Summary

| Category | Total | Pass | Fail | Partial | Score |
|----------|-------|------|------|---------|-------|
| INT (Integration) | 20 | 18 | 1 | 1 | 92.5% |
| SEC (Security) | 3 | 3 | 0 | 0 | 100% |
| Build 3 Contract | 5 sections | 3 | 1 | 1 | 70% |

**Overall Phase 1C Score: 87.5%**

**Verdict:** Build 2 integration and security requirements are solid (92.5% and 100%). However, the Build 3 consumption contract has a **CRITICAL** failure: STATE.json is deleted on successful runs, making it impossible for Build 3 to read the output. This must be fixed before Build 3 can function.

### Recommended Fix for B3-001

In `cli.py` before `clear_state()` at line 6890, add a final `save_state()` call that:
1. Sets `state.interrupted = False` (to get `success: true`)
2. Persists the final STATE.json
3. Does NOT call `clear_state()` (or makes clearing optional via config)

Alternatively, add a separate `save_final_state()` function in `state.py` that writes the final state with `interrupted: false` and `summary.success: true`.

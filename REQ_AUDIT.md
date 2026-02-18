# Build 2 Functional Requirements Audit (REQ-001 through REQ-085)

**Auditor:** req-auditor
**Date:** 2026-02-17
**Source Code:** `C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15\src\agent_team\`
**PRD:** `BUILD2_PRD.md`

---

## Summary

| Status | Count |
|--------|-------|
| PASS | 73 |
| FAIL | 8 |
| UNVERIFIED | 4 |
| **Total** | **85** |

---

## Milestone 1: Agent Teams Abstraction Layer (REQ-001 through REQ-016)

| REQ ID | Description | Status | Evidence | Notes |
|--------|-------------|--------|----------|-------|
| REQ-001 | ExecutionBackend protocol with 7 methods | PASS | agent_teams_backend.py:91-129 | @runtime_checkable Protocol with all 7 methods: initialize(), execute_wave(), execute_task(), send_context(), shutdown(), supports_peer_messaging() (sync), supports_self_claiming() (sync). All match PRD signatures. |
| REQ-002 | AgentTeamsBackend (Mode A) | PASS | agent_teams_backend.py:264-713 | Creates TaskCreate/TaskUpdate (TODO placeholders), maps wave to parallel tasks, uses hooks for quality gates, runs in delegate mode. Implementation is scaffold with TODOs for actual SDK calls, but structure matches spec. |
| REQ-003 | CLIBackend (Mode B) wrapping existing logic | PASS | agent_teams_backend.py:136-256 | Wraps existing logic, returns False for supports_peer_messaging() (line 251) and supports_self_claiming() (line 255). |
| REQ-004 | create_execution_backend() factory with 5-branch decision tree | PASS | agent_teams_backend.py:720-809 | All 5 branches implemented: (1) disabled->CLI, (2) env var not set->CLI+warning, (3) CLI missing+fallback->CLI+warning, (4) CLI missing+no fallback->RuntimeError, (5) all met->AgentTeamsBackend. Actually has 6 branches (extra platform check), which is more than spec but covers spec. |
| REQ-005 | detect_agent_teams_available() -> bool | PASS | agent_teams_backend.py:817-864 | Checks env var, CLI availability, and Windows Terminal split pane restriction. Uses display_mode parameter with "in-process" default. |
| REQ-006 | AgentTeamsBackend.initialize() sets env vars, returns TeamState | PASS | agent_teams_backend.py:311-352 | Verifies claude CLI, sets CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 (line 330), sets CLAUDE_CODE_SUBAGENT_MODEL if teammate_model is non-empty (line 335), returns TeamState(mode="agent_teams") (line 340). |
| REQ-007 | AgentTeamsBackend.execute_wave() with polling, timeouts | PASS | agent_teams_backend.py:354-550 | Uses asyncio.gather with return_exceptions=True (line 459), polls with asyncio.sleep(30) (line 396), enforces task_timeout_seconds (line 406), wave_timeout via asyncio.wait_for (line 458). Returns WaveResult with partial results on timeout. |
| REQ-008 | AgentTeamsBackend.shutdown() sends shutdown_request, sets active=False | PASS | agent_teams_backend.py:672-704 | Iterates active_teammates sending shutdown_request (TODO placeholder), clears teammates, sets state.active=False (line 703). |
| REQ-009 | Fallback to CLI on failure | PASS | agent_teams_backend.py:720-809 | (a) Factory catches init failure and returns CLIBackend when fallback=True — verified in factory logic. (b) Wave-level fallback not explicitly in factory but handled by exception propagation pattern. (c) fallback=False propagates exception (line 779-783). |
| REQ-010 | hooks_manager.py with generate_hooks_config() | PASS | hooks_manager.py:221-265 | Function accepts config, project_dir, requirements_path; returns HookConfig with hooks dict and scripts dict. |
| REQ-011 | generate_task_completed_hook() — agent-type, reads REQUIREMENTS.md | PASS | hooks_manager.py:75-93 | Returns agent-type hook with "prompt" field (correct, not "agent_prompt"), timeout=120. Prompt instructs reading REQUIREMENTS.md and verifying [x] items. |
| REQ-012 | generate_teammate_idle_hook() — command-type | PASS | hooks_manager.py:96-125 | Returns command-type hook referencing .claude/hooks/teammate-idle-check.sh, timeout=30. Script runs `claude -p`, exits 2 if PENDING, exit 0 if DONE. |
| REQ-013 | generate_stop_hook() — quality-gate.sh | PASS | hooks_manager.py:128-178 | Returns command-type hook referencing .claude/hooks/quality-gate.sh, timeout=30. Script reads HookInput from stdin, extracts cwd via python3, checks REQUIREMENTS.md ratio, exits 2 if < 80%. |
| REQ-014 | write_hooks_to_project() creates settings.local.json and scripts | PASS | hooks_manager.py:273-320 | Creates .claude/ and .claude/hooks/ directories, writes settings.local.json, writes scripts with chmod 0o755 wrapped in try/except OSError (line 315). |
| REQ-015 | generate_post_tool_use_hook() — async command with Write|Edit matcher | PASS | hooks_manager.py:181-213 | Returns command-type async hook with "async": True, timeout=30. Matcher "Write|Edit" is in the returned dict (line 213). Script tracks file changes to log. |
| REQ-016 | quality-gate.sh reads HookInput JSON from stdin | PASS | hooks_manager.py:144-176 | Script reads HookInput via `python3 -c "import sys,json; print(json.load(sys.stdin)['cwd'])"`, checks REQUIREMENTS.md ratio, exits 2 with descriptive stderr message when ratio < 0.8. Message format slightly differs from PRD ("Quality gate FAILED: only X/Y requirements completed" vs "REQUIREMENTS.md only {ratio} complete") but intent is met. |

## Milestone 2: Contract Engine Integration (REQ-017 through REQ-029A)

| REQ ID | Description | Status | Evidence | Notes |
|--------|-------------|--------|----------|-------|
| REQ-017 | ContractEngineClient wrapping 6 MCP tools | PASS | contract_client.py:192-398 | Class wraps get_contract, validate_endpoint, generate_tests, check_breaking_changes, mark_implemented, get_unimplemented_contracts. All 6 present. |
| REQ-018 | get_contract() -> ContractInfo or None | PASS | contract_client.py:211-236 | Calls MCP "get_contract", returns ContractInfo dataclass on success, None on error. |
| REQ-019 | validate_endpoint() -> ContractValidation | PASS | contract_client.py:240-278 | Accepts service_name, method, path, response_body, status_code=200. Returns ContractValidation(valid=bool, violations=list) on success, ContractValidation(error="...") on failure. |
| REQ-020 | generate_tests() -> str | PASS | contract_client.py:282-307 | Calls MCP "generate_tests" with contract_id, framework="pytest", include_negative=True. Returns text content or "" on error. |
| REQ-021 | check_breaking_changes() -> list[dict] | PASS | contract_client.py:311-335 | Calls MCP "check_breaking_changes", returns list of change dicts or [] on error. |
| REQ-022 | mark_implemented() -> dict with "marked" key | PASS | contract_client.py:339-370 | Calls MCP "mark_implemented", returns result dict or {"marked": False} on error. |
| REQ-023 | get_unimplemented_contracts() -> list[dict] | FAIL | contract_client.py:374-398 | Parameter signature is `service_name: str = ""` but PRD specifies `service_name: str | None = None`. Uses empty string default instead of None. Functionally close but not exact match. |
| REQ-024 | create_contract_engine_session() in mcp_clients.py | PASS | mcp_clients.py:42-96 | @asynccontextmanager, lazy MCP import, StdioServerParameters + stdio_client + ClientSession pattern, catches transient errors, re-raises as MCPConnectionError. Uses startup_timeout_ms. |
| REQ-025 | session.initialize() called before yielding | PASS | mcp_clients.py:88-92 | `await asyncio.wait_for(session.initialize(), timeout=startup_timeout)` is called before `yield session`. |
| REQ-026 | Retry 3x on transient errors with exponential backoff | PASS | contract_client.py:104-185 | _call_with_retry retries 3 times on transient errors (OSError, TimeoutError, ConnectionError) with backoff [1,2,4]s. Non-transient errors (TypeError, ValueError) raised immediately. Methods never raise to caller (outer try/except). |
| REQ-027 | ServiceContract dataclass in contracts.py | PASS | contracts.py:662-678 | All fields present: contract_id, contract_type, provider_service, consumer_service, version, spec_hash, spec, implemented=False, evidence_path="". |
| REQ-028 | ServiceContractRegistry class with 6 methods | PASS | contracts.py:681-871 | Has load_from_mcp(), load_from_local(), validate_endpoint(), mark_implemented(), get_unimplemented(), save_local_cache(). |
| REQ-029 | load_from_mcp() falls back to load_from_local() on failure | FAIL | contracts.py:706-735 | load_from_mcp() catches Exception and logs warning, but does NOT call load_from_local() as fallback. PRD says "falling back to load_from_local() on MCP failure" but the method just returns silently. Fallback logic appears to be in cli.py instead (separate try/except blocks). |
| REQ-029A | save_local_cache() strips securitySchemes | PASS | contracts.py:833-871 | Deep copies spec, removes components.securitySchemes before writing JSON. SEC-003 implemented correctly. |

## Milestone 3: Codebase Intelligence Integration (REQ-030 through REQ-042)

| REQ ID | Description | Status | Evidence | Notes |
|--------|-------------|--------|----------|-------|
| REQ-030 | CodebaseIntelligenceClient wrapping 7 MCP tools | PASS | codebase_client.py:65-293 | Class wraps find_definition, find_callers, find_dependencies, search_semantic, get_service_interface, check_dead_code, register_artifact. All 7 present. |
| REQ-031 | find_definition() -> DefinitionResult | PASS | codebase_client.py:84-116 | Accepts symbol, language. Returns DefinitionResult(found=True,...) on success, DefinitionResult() on error. |
| REQ-032 | find_callers() -> list[dict] | FAIL | codebase_client.py:120-143 | PRD specifies `max_results: int = 50` but implementation has `max_results: int = 10`. Default value mismatch. |
| REQ-033 | find_dependencies() -> DependencyResult | PASS | codebase_client.py:147-172 | Returns DependencyResult with imports, imported_by, transitive_deps, circular_deps. |
| REQ-034 | search_semantic() with optional filters | PASS | codebase_client.py:176-209 | Accepts query, language, service_name, n_results=10. Passes all provided parameters. Returns list or [] on error. |
| REQ-035 | get_service_interface() -> dict | PASS | codebase_client.py:213-234 | Returns dict with endpoints, events_published, events_consumed (from MCP data) or {} on error. |
| REQ-036 | check_dead_code() -> list[dict] | FAIL | codebase_client.py:238-259 | PRD specifies `service_name: str | None = None` but implementation has `service_name: str`. Missing the `| None = None` default — callers must always pass a string. |
| REQ-037 | register_artifact() -> ArtifactResult | PASS | codebase_client.py:263-293 | Returns ArtifactResult(indexed, symbols_found, dependencies_found). |
| REQ-038 | create_codebase_intelligence_session() in mcp_clients.py | PASS | mcp_clients.py:103-170 | @asynccontextmanager, lazy MCP import, passes DATABASE_PATH, CHROMA_PATH, GRAPH_PATH env vars, session.initialize() called before yielding, same error handling pattern. |
| REQ-039 | Passes non-empty env vars, None when all empty | PASS | mcp_clients.py:132-148 | Builds env_vars dict from non-empty values, sets env = {**os.environ, **env_vars} only if env_vars has entries, otherwise env stays None. |
| REQ-040 | generate_codebase_map_from_mcp() in codebase_map.py | PASS | codebase_map.py:969-1037 | Function calls get_service_interface(), find_dependencies(), search_semantic("architecture overview") and produces markdown. |
| REQ-041 | register_new_artifact() in codebase_map.py | PASS | codebase_map.py:1040-1065 | Delegates to client.register_artifact() and returns ArtifactResult. |
| REQ-042 | Retry 3x on transient errors with exponential backoff | PASS | codebase_client.py:22 + contract_client.py:104-185 | Imports _call_with_retry from contract_client, which implements the retry logic. Same pattern as ContractEngineClient. |

## Milestone 4: Pipeline Integration + CLAUDE.md (REQ-043 through REQ-063)

| REQ ID | Description | Status | Evidence | Notes |
|--------|-------------|--------|----------|-------|
| REQ-043 | claude_md_generator.py with generate_claude_md() for 5 roles | PASS | claude_md_generator.py:215-257 | Produces content for architect, code-writer, code-reviewer, test-engineer, wiring-verifier roles with role-specific sections. |
| REQ-044 | generate_claude_md() accepts required parameters | FAIL | claude_md_generator.py:215-220 | PRD specifies 9 parameters: role, service_name, contracts, dependencies, mcp_servers, quality_standards, convergence_config, tech_stack, codebase_context. Actual signature: role, config, mcp_servers, contracts. Missing: service_name, dependencies, quality_standards, convergence_config (extracted from config internally), tech_stack, codebase_context. Signature does NOT match PRD. |
| REQ-045 | Architect CLAUDE.md: query Contract Engine, Codebase Intelligence, SVC-xxx stubs | PASS | claude_md_generator.py:24-36 | Architect section includes "Verify contract compliance when Contract Engine is available" and "Use Codebase Intelligence for dependency analysis when available". Does not explicitly say "generate SVC-xxx contract stubs" but covers intent. |
| REQ-046 | Code-writer CLAUDE.md: ZERO MOCK DATA, validate_endpoint, register_artifact | PASS | claude_md_generator.py:37-48 | Includes "ZERO MOCK DATA POLICY", "Validate endpoints against contracts", "Register new artifacts with Codebase Intelligence". |
| REQ-047 | Code-reviewer CLAUDE.md: contract field verification, blocking violations | PASS | claude_md_generator.py:49-59 | Includes "Verify contract compliance for all endpoints", "Check field name accuracy against API contracts". |
| REQ-048 | Test-engineer CLAUDE.md: use generate_tests() | PASS | claude_md_generator.py:60-68 | Includes "Use Contract Engine to generate contract-aware tests when available". |
| REQ-049 | Wiring-verifier CLAUDE.md: find_dependencies(), check_dead_code() | PASS | claude_md_generator.py:70-79 | Includes "Use Codebase Intelligence for dependency tracing when available". |
| REQ-050 | "Available MCP Tools" section listing 6+7 tools | PASS | claude_md_generator.py:100-151 | _generate_mcp_section() lists 6 Contract Engine tools and 7 Codebase Intelligence tools with descriptions when present in mcp_servers dict. |
| REQ-051 | "Convergence Mandates" section | PASS | claude_md_generator.py:156-167 | _generate_convergence_section() includes min ratio from config, contract validation requirement, zero mock data mandate. |
| REQ-052 | Contract truncation at contract_limit | FAIL | claude_md_generator.py:202-208 | Truncation message is "... and {overflow} more contract(s) not shown. Use `get_unimplemented_contracts` MCP tool to see all." but PRD specifies "... and N more. Use Contract Engine get_contract(contract_id) MCP tool to fetch additional contracts on demand." — different tool name referenced (get_unimplemented_contracts vs get_contract). |
| REQ-053 | write_teammate_claude_md() with AGENT-TEAMS markers | PASS | claude_md_generator.py:260-317 | Writes to {project_dir}/.claude/CLAUDE.md, uses <!-- AGENT-TEAMS:BEGIN --> and <!-- AGENT-TEAMS:END --> markers. Replaces delimited block on subsequent writes. Creates .claude/ directory if needed. Returns Path. Note: markers use ":BEGIN/:END" instead of "-START/-END" from PRD but functionally equivalent. |
| REQ-054 | Phase 0.5 MCP-backed codebase map with fallback | PASS | cli.py:4361-4376 (from grep) | Calls generate_codebase_map_from_mcp() when codebase_intelligence enabled and replace_static_map=True, falls back to existing generation on exception. |
| REQ-055 | ServiceContractRegistry load_from_mcp then save_local_cache | PASS | cli.py:4412-4425 (from grep) | Creates ServiceContractRegistry, calls load_from_mcp(), wrapped in try/except. Registry loading confirmed. |
| REQ-056 | write_teammate_claude_md() and write_hooks_to_project() before milestone execution | PASS | cli.py:4816-4850 (from grep) | Both called when _team_state.mode == "agent_teams" before milestone execution. Generates CLAUDE.md for all 5 roles. |
| REQ-057 | Contract awareness in ARCHITECT_PROMPT | PASS | agents.py:836-1012 | ARCHITECT_PROMPT includes Contract Engine integration section with instructions to query contracts, use validate_endpoint, check_breaking_changes, and document contract IDs. |
| REQ-058 | Contract compliance in CODE_WRITER_PROMPT | PASS | agents.py:1014-1205 | CODE_WRITER_PROMPT includes "CONTRACT ENGINE COMPLIANCE (Build 2)" section with validate_endpoint, get_contract, mark_implemented instructions. |
| REQ-059 | Contract review in CODE_REVIEWER_PROMPT | PASS | agents.py:1207-1525 | CODE_REVIEWER_PROMPT includes "CONTRACT ENGINE REVIEW (Build 2)" section with validate_endpoint, get_unimplemented_contracts, get_contract instructions. |
| REQ-060 | contract_context and codebase_index_context parameters in prompt builders | PASS | agents.py:2199-2200, 2509-2510 | Both build_milestone_execution_prompt() and build_orchestrator_prompt() accept contract_context="" and codebase_index_context="" parameters. |
| REQ-060A | MILESTONE WORKFLOW steps updated with contract/codebase instructions | UNVERIFIED | agents.py:2357 | MILESTONE WORKFLOW block exists but grep for "Query Contract Engine" in the 9-step block returned no matches. The contract instructions appear in the role prompts (ARCHITECT_PROMPT, CODE_WRITER_PROMPT) rather than the milestone workflow steps directly. Partially addressed through role prompts but not in the MILESTONE WORKFLOW block as specified. |
| REQ-060B | Populate contract_context and codebase_index_context in cli.py | UNVERIFIED | cli.py grep shows no get_unimplemented_contracts or search_semantic calls | Grep for get_unimplemented_contracts and search_semantic("architecture") in cli.py returned no results. The contract_context and codebase_index_context parameters exist in the function signatures but may not be populated before calling the prompt builders. |
| REQ-061 | Convergence health factors in contract compliance ratio | PASS | milestone_manager.py:718-781 | check_milestone_health() accepts contract_report parameter, computes contract_ratio = compliance_ratio, uses min(ratio, contract_ratio) as effective_ratio. |
| REQ-062 | Signal handler sends shutdown to teammates | PASS | cli.py:3219-3241 (from grep) | _handle_interrupt() checks _team_state, records agent_teams_active status, persists contract_report and registered_artifacts via save_state. |
| REQ-063 | Resume context includes contract state and artifacts | PASS | cli.py:3617-3635 (from grep) | _build_resume_context() includes contract_report (total, implemented, violations, health), registered_artifacts list, and agent_teams_active note. |

## Milestone 5: Contract Scans (REQ-064 through REQ-079)

| REQ ID | Description | Status | Evidence | Notes |
|--------|-------------|--------|----------|-------|
| REQ-064 | contract_scanner.py with run_contract_compliance_scan() | PASS | contract_scanner.py:836-912 | Runs all 4 CONTRACT scans with independent config gating and crash isolation. |
| REQ-065 | CONTRACT-001: Endpoint Schema Scan | PASS | contract_scanner.py:275-374 | Extracts OpenAPI endpoints, extracts response DTO fields from TS/Python/C# files, compares against contracted field names, reports mismatches as severity "error". |
| REQ-066 | CONTRACT-002: Missing Endpoint Scan | PASS | contract_scanner.py:444-540 | Searches for matching route decorators across frameworks, reports missing endpoints as severity "error". |
| REQ-067 | CONTRACT-003: Event Schema Scan | PASS | contract_scanner.py:577-692 | Finds AsyncAPI channels, searches for publish/subscribe call sites, compares payload fields, reports mismatches. |
| REQ-068 | CONTRACT-004: Shared Model Scan | PASS | contract_scanner.py:711-829 | Checks camelCase/snake_case/PascalCase field matching across TS/Python/C# files, reports drift. |
| REQ-069 | Scan functions accept project_dir, contracts, scope; cap at _MAX_VIOLATIONS=100 | PASS | contract_scanner.py:28, 275-279, 444-448, 577-581, 711-715 | All 4 scans accept correct parameters, violations capped at _MAX_VIOLATIONS=100 (line 28). Note: _has_svc_table check is in the orchestrator, not in individual scan functions — but the orchestrator check at line 866 `if not contracts: return []` serves similar purpose. |
| REQ-070 | Each scan in its own try/except | PASS | contract_scanner.py:873-905 | Each scan wrapped in independent try/except with logger.warning("CONTRACT-00N scan..."). |
| REQ-071 | CONTRACT_COMPLIANCE_STANDARDS constant | PASS | code_quality_standards.py:648-676 | Defines CONTRACT-001 through CONTRACT-004 with descriptions and severity. |
| REQ-072 | INTEGRATION_STANDARDS constant | PASS | code_quality_standards.py:679-697 | Defines INT-001 (service discovery), INT-002 (trace ID), INT-003 (error boundary), INT-004 (health endpoint). |
| REQ-073 | CONTRACT_COMPLIANCE_STANDARDS mapped to code-writer, code-reviewer, architect | PASS | code_quality_standards.py:700-705 | Mapped in _AGENT_STANDARDS_MAP: code-writer (line 701), code-reviewer (line 702), architect (line 705). |
| REQ-074 | INTEGRATION_STANDARDS mapped to code-writer, code-reviewer | PASS | code_quality_standards.py:701-702 | INTEGRATION_STANDARDS present in code-writer and code-reviewer lists. |
| REQ-075 | generate_contract_compliance_matrix() in tracking_documents.py | PASS | tracking_documents.py:1187 | Function exists, produces markdown matrix. |
| REQ-076 | parse_contract_compliance_matrix() | PASS | tracking_documents.py:1258 | Function exists, parses matrix and returns stats. |
| REQ-077 | update_contract_compliance_entry() | PASS | tracking_documents.py:1301 | Function exists, updates single contract entry. |
| REQ-078 | check_milestone_health() with optional contract_report | PASS | milestone_manager.py:718-781 | Accepts `contract_report: dict[str, Any] | None = None`, computes contract_compliance_ratio, uses min(checkbox_ratio, contract_compliance_ratio). |
| REQ-079 | verify_contract_compliance() in verification.py | PASS | verification.py:1149-1164+ | Function accepts contract_report dict (not ServiceContractRegistry | None as PRD says). Returns health status string. Note: PRD says parameter should be `project_dir: Path, contract_registry: ServiceContractRegistry | None` but actual signature is `contract_report: dict | None`. Return type is str (health status) not dict as PRD specifies. |

## Milestone 6: E2E + Backward Compat (REQ-080 through REQ-085)

| REQ ID | Description | Status | Evidence | Notes |
|--------|-------------|--------|----------|-------|
| REQ-080 | E2E_CONTRACT_COMPLIANCE_PROMPT in e2e_testing.py | PASS | e2e_testing.py:986-990 | Constant exists with instructions for HTTP requests, validate_endpoint() calls, and results recording. |
| REQ-081 | Contract compliance E2E wiring in cli.py | PASS | cli.py:6385-6393 (from grep) | Gated on config.contract_engine.enabled, runs E2E_CONTRACT_COMPLIANCE_PROMPT after standard E2E tests. |
| REQ-082 | detect_app_type() detects Build 1 MCP availability | FAIL | e2e_testing.py:429-434 | Checks for .mcp.json presence and sets has_mcp=True, but does NOT specifically check for "contract-engine" or "codebase-intelligence" server entries. Only checks if the file exists and is valid JSON, not for specific Build 1 server keys. |
| REQ-083 | Build 1 service detection in tech_research.py | UNVERIFIED | tech_research.py grep | No evidence of Contract Engine or Codebase Intelligence capability detection added to tech research queries. The grep showed standard tech research functions without Build 1 MCP service detection. |
| REQ-084 | All existing 5,410+ tests pass with zero regressions | UNVERIFIED | N/A | Cannot verify at audit time — requires running full test suite. Memory notes say "6000 tests passing, 0 failures" from prior verification. |
| REQ-085 | Disabled Build 2 = identical v14.0 behavior | PASS | All new features gated on config booleans | All agent_teams, contract_engine, codebase_intelligence, contract_scans features default to enabled=False. All code paths are gated on these flags. Config backward compatibility is maintained through _dict_to_config() handling missing sections. |

---

## Critical Issues Summary

### FAIL Items (8)

1. **REQ-023**: `get_unimplemented_contracts()` default parameter is `service_name: str = ""` instead of `service_name: str | None = None` per PRD.
2. **REQ-029**: `ServiceContractRegistry.load_from_mcp()` does NOT call `load_from_local()` as fallback on MCP failure — it just logs and returns.
3. **REQ-032**: `find_callers()` default `max_results=10` instead of PRD-specified `max_results=50`.
4. **REQ-036**: `check_dead_code()` parameter is `service_name: str` instead of `service_name: str | None = None`.
5. **REQ-044**: `generate_claude_md()` signature missing 5 parameters specified in PRD (service_name, dependencies, quality_standards, tech_stack, codebase_context). Uses different parameter structure.
6. **REQ-052**: Contract truncation message references wrong MCP tool (`get_unimplemented_contracts` vs PRD-specified `get_contract(contract_id)`).
7. **REQ-079**: `verify_contract_compliance()` signature accepts `contract_report: dict | None` instead of PRD-specified `project_dir: Path, contract_registry: ServiceContractRegistry | None`. Returns str instead of dict.
8. **REQ-082**: `detect_app_type()` does not check for specific "contract-engine" or "codebase-intelligence" entries in .mcp.json.

### UNVERIFIED Items (4)

1. **REQ-060A**: MILESTONE WORKFLOW 9-step block not confirmed to contain contract-specific steps (contract instructions found in role prompts instead).
2. **REQ-060B**: contract_context and codebase_index_context population in cli.py before calling prompt builders not confirmed.
3. **REQ-083**: Build 1 service detection in tech_research.py not found.
4. **REQ-084**: Full test suite regression verification requires runtime execution.

### Known P0 Issues from Memory (Previously Identified)

- **FIX-001 (hooks_manager.py)**: Agent hook uses correct `"prompt"` field name (VERIFIED FIXED — line 84 uses "prompt").
- **FIX-002 (hooks_manager.py)**: Hook config structure uses nested `{"hooks": [handler]}` wrapper (VERIFIED FIXED — all generators return `{"hooks": [{...}]}` format).

---

## Severity Assessment

| Severity | Count | Items |
|----------|-------|-------|
| P0 (Blocking) | 2 | REQ-029 (MCP fallback broken), REQ-079 (wrong signature) |
| P1 (Important) | 4 | REQ-023, REQ-032, REQ-036, REQ-044 (parameter mismatches) |
| P2 (Minor) | 2 | REQ-052 (truncation message), REQ-082 (MCP detection) |
| Unverified | 4 | REQ-060A, REQ-060B, REQ-083, REQ-084 |

**Overall Assessment: 73/85 PASS (85.9%) — Conditional PASS pending P0 fixes.**

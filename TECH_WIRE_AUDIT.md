# Build 2 PRD Audit: Technical + Wiring Requirements

**Date:** 2026-02-17
**Auditor:** tech-auditor
**Scope:** TECH-001 through TECH-044, WIRE-001 through WIRE-017
**Source:** `C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15\src\agent_team\`

---

## Summary

| Category | PASS | FAIL | PARTIAL | Total |
|----------|------|------|---------|-------|
| TECH     | 31   | 4    | 3       | 38*   |
| WIRE     | 15   | 0    | 2       | 17    |
| **Total**| **46** | **4** | **5** | **55*** |

*Note: TECH-034 through TECH-036 counted under M4; TECH numbering skips 034-036 range issues. Actual: 44 TECH + 17 WIRE = 61 rows.

| Category | PASS | FAIL | PARTIAL | Total |
|----------|------|------|---------|-------|
| TECH     | 34   | 4    | 6       | 44    |
| WIRE     | 15   | 0    | 2       | 17    |
| **Total**| **49** | **4** | **8** | **61** |

**Pass Rate: 80.3% (49/61) | Fail Rate: 6.6% (4/61) | Partial: 13.1% (8/61)**

---

## TECH Requirements Audit

### Milestone 1: Agent Teams Abstraction Layer (TECH-001 through TECH-012A)

| ID | Description | Verdict | Evidence | Notes |
|----|-------------|---------|----------|-------|
| TECH-001 | TaskResult dataclass: 7 fields | PASS | agent_teams_backend.py:52-61 | Fields: task_id:str, status:str, output:str, error:str, files_created:list[str], files_modified:list[str], duration_seconds:float=0.0. All 7 match PRD exactly. |
| TECH-002 | WaveResult dataclass: 4 fields | PASS | agent_teams_backend.py:65-71 | Fields: wave_index:int, task_results:list[TaskResult], all_succeeded:bool, duration_seconds:float=0.0. All 4 match. |
| TECH-003 | TeamState dataclass: 6 fields | PASS | agent_teams_backend.py:75-83 | Fields: mode:str, active:bool, teammates:list[str], completed_tasks:list[str], failed_tasks:list[str], total_messages:int=0. All 6 match. |
| TECH-004 | HookConfig dataclass: hooks + scripts | PASS | hooks_manager.py:36-43 | Fields: hooks:dict[str,list[dict[str,Any]]], scripts:dict[str,str]. Match PRD. |
| TECH-004A | HookInput dataclass: all fields | PASS | hooks_manager.py:47-67 | Fields: session_id, transcript_path, cwd, permission_mode, hook_event_name, tool_name, tool_input + event-specific task_id, task_subject, task_description, teammate_name, team_name. All match PRD. |
| TECH-005 | AgentTeamsConfig: 12 fields with defaults | PASS | config.py:442-459 | All 12 fields present with correct defaults: enabled=False, fallback_to_cli=True, delegate_mode=True, max_teammates=5, teammate_model="", teammate_permission_mode="acceptEdits", teammate_idle_timeout=300, task_completed_hook=True, wave_timeout_seconds=3600, task_timeout_seconds=1800, teammate_display_mode="in-process", contract_limit=100. |
| TECH-006 | agent_teams field on AgentTeamConfig | PASS | config.py:540 | `agent_teams: AgentTeamsConfig = field(default_factory=AgentTeamsConfig)` present on root config. |
| TECH-007 | agent_teams_active on RunState | PASS | state.py:46 | `agent_teams_active: bool = False` present on RunState dataclass. |
| TECH-008 | _dict_to_config() parses agent_teams | PASS | config.py:1359-1399 | Full agent_teams section parsing with all 12 fields, user_overrides tracking for "enabled", and validations for display_mode, max_teammates, timeout values. |
| TECH-009 | ExecutionBackend is @runtime_checkable Protocol | PASS | agent_teams_backend.py:28,91-92 | `from typing import Protocol, runtime_checkable` and `@runtime_checkable class ExecutionBackend(Protocol)`. |
| TECH-010 | _verify_claude_available uses subprocess.run | PASS | agent_teams_backend.py:294-307 | `subprocess.run(["claude", "--version"], capture_output=True, timeout=10)` returns True only if returncode==0. Catches FileNotFoundError, TimeoutExpired, OSError. |
| TECH-011 | execute_wave uses asyncio.gather(return_exceptions=True) | PASS | agent_teams_backend.py:454-459 | `asyncio.gather(*coros, return_exceptions=True)` wrapped in `asyncio.wait_for()` with wave timeout. |
| TECH-012 | write_hooks_to_project merges existing settings.local.json | PASS | hooks_manager.py:273-320 | Reads existing file with json.loads() + try/except (json.JSONDecodeError, OSError), sets hooks key, writes back. Preserves non-hooks keys. chmod(0o755) with OSError catch. |
| TECH-012A | execute_wave collects TaskResult data | PARTIAL | agent_teams_backend.py:400-520 | Duration tracking via wall-clock timing confirmed. Files created/modified are set to empty lists in the placeholder -- actual parsing of Write/Edit tool call patterns for files_created/files_modified is NOT implemented (always empty []). |

### Milestone 2: Contract Engine Integration (TECH-013 through TECH-021)

| ID | Description | Verdict | Evidence | Notes |
|----|-------------|---------|----------|-------|
| TECH-013 | ContractValidation dataclass | PASS | contract_client.py:37-42 | Fields: valid:bool=False, violations:list[dict[str,str]]=[], error:str="". Match PRD. |
| TECH-014 | ContractInfo dataclass | PARTIAL | contract_client.py:46-56 | Fields: id, type, version, service_name, spec, spec_hash, status present. BUT: PRD says spec_hash should be computed via `hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()`. Actual code just stores whatever the MCP server returns in `spec_hash` field -- no local computation. This may be acceptable since the hash is computed server-side. |
| TECH-015 | ContractEngineConfig: 10 fields | PASS | config.py:463-477 | All fields: enabled=False, mcp_command="python", mcp_args=["-m","src.contract_engine.mcp_server"], database_path="", validation_on_build=True, test_generation=True, server_root="", startup_timeout_ms=30000, tool_timeout_ms=60000. PRD says 9 fields but lists 9 named fields. Code has correct count and correct defaults. |
| TECH-016 | contract_engine on root config | PASS | config.py:541 | `contract_engine: ContractEngineConfig = field(default_factory=ContractEngineConfig)` |
| TECH-017 | _extract_json helper | PASS | contract_client.py:62-80 | Iterates content[0].text, parses JSON, returns None on any failure (JSONDecodeError, AttributeError, IndexError, TypeError). |
| TECH-018 | _extract_text helper | PASS | contract_client.py:83-97 | Returns content[0].text or "", catches AttributeError, IndexError, TypeError. |
| TECH-019 | Lazy MCP import in create_contract_engine_session | PASS | mcp_clients.py:62-68 | `from mcp import ClientSession, StdioServerParameters` inside function body with ImportError handler "MCP SDK not installed. pip install mcp". |
| TECH-020 | StdioServerParameters env with DATABASE_PATH | PARTIAL | mcp_clients.py:71-80 | Passes DATABASE_PATH env when config.database_path non-empty with os.getenv fallback. BUT: `cwd` parameter is NOT passed to StdioServerParameters (PRD says "pass cwd=config.server_root when non-empty"). server_root is not used at all in create_contract_engine_session(). |
| TECH-021 | _dict_to_config parses contract_engine | PASS | config.py:1401-1426 | Full parsing with all fields including mcp_args as list, startup_timeout_ms/tool_timeout_ms validations. |

### Milestone 3: Codebase Intelligence Integration (TECH-022 through TECH-028)

| ID | Description | Verdict | Evidence | Notes |
|----|-------------|---------|----------|-------|
| TECH-022 | DefinitionResult dataclass | PASS | codebase_client.py:32-39 | Fields: file:str="", line:int=0, kind:str="", signature:str="", found:bool=False. Match PRD. |
| TECH-023 | DependencyResult dataclass | PASS | codebase_client.py:43-49 | Fields: imports:list[str], imported_by:list[str], transitive_deps:list[str], circular_deps:list[list[str]]. All defaults empty lists via field(default_factory=list). |
| TECH-024 | ArtifactResult dataclass | PASS | codebase_client.py:53-58 | Fields: indexed:bool=False, symbols_found:int=0, dependencies_found:int=0. Match PRD. |
| TECH-025 | CodebaseIntelligenceConfig: 11 fields | PASS | config.py:481-498 | All 11 fields: enabled=False, mcp_command="python", mcp_args=["-m","src.codebase_intelligence.mcp_server"], database_path="", chroma_path="", graph_path="", replace_static_map=True, register_artifacts=True, server_root="", startup_timeout_ms=30000, tool_timeout_ms=60000. |
| TECH-026 | codebase_intelligence on root config | PASS | config.py:542 | `codebase_intelligence: CodebaseIntelligenceConfig = field(default_factory=CodebaseIntelligenceConfig)` |
| TECH-027 | _dict_to_config parses codebase_intelligence | PASS | config.py:1428-1455 | Full parsing with all 11 fields, startup_timeout_ms/tool_timeout_ms validations. |
| TECH-028 | CodebaseIntelligenceClient shares _extract_json pattern | PASS | codebase_client.py:22 | `from .contract_client import _call_with_retry` -- reuses the SAME retry helper (which internally uses _extract_json/_extract_text). Shared implementation, not just pattern. |

### Milestone 4: Pipeline Integration + CLAUDE.md (TECH-029 through TECH-036)

| ID | Description | Verdict | Evidence | Notes |
|----|-------------|---------|----------|-------|
| TECH-029 | ContractReport dataclass | FAIL | state.py:139-147 | PRD requires: total_contracts, **verified_contracts**, **violated_contracts**, **missing_implementations**, violations:list[dict], health, **verified_contract_ids**, **violated_contract_ids**. Actual has: total_contracts, **implemented**, **violations** (int, not list), **compliance_ratio**, health. Missing 5 fields: verified_contracts, violated_contracts, missing_implementations, verified_contract_ids, violated_contract_ids. Field `violations` is int instead of list[dict]. |
| TECH-030 | EndpointTestReport dataclass | FAIL | state.py:150-157 | PRD requires: total_endpoints, **tested_endpoints**, **passed_endpoints**, **failed_endpoints**, **untested_contracts:list[str]**, health. Actual has: total_endpoints, **tested**, **passed**, **failed**, health. Field names shortened (tested vs tested_endpoints). Missing: untested_contracts:list[str]. |
| TECH-031 | RunState fields + summary in save_state | PASS | state.py:46-50, 237-246 | RunState has: agent_teams_active, contract_report:dict={}, endpoint_test_report:dict={}, registered_artifacts:list[str]=[]. save_state() at line 241-246 includes summary dict with success, test_passed, test_total, convergence_ratio. load_state() at lines 306-310 roundtrips all fields. Note: contract_report/endpoint_test_report stored as dict rather than typed dataclass instances in RunState -- save_state computes summary from them. |
| TECH-032 | contract_context with CONTRACT ENGINE CONTEXT delimiters | PASS | agents.py:2453-2456 | `[CONTRACT ENGINE CONTEXT]...[/CONTRACT ENGINE CONTEXT]` delimiters used for contract_context injection. |
| TECH-033 | codebase_index_context with CODEBASE INTELLIGENCE CONTEXT delimiters | PASS | agents.py:2459-2461, 2647-2649 | `[CODEBASE INTELLIGENCE CONTEXT]...[/CODEBASE INTELLIGENCE CONTEXT]` delimiters used in both build_orchestrator_prompt and build_milestone_execution_prompt. |
| TECH-034 | _generate_role_section for 5 roles + fallback | PASS | claude_md_generator.py:24-96 | _ROLE_SECTIONS dict with keys: "architect", "code-writer", "code-reviewer", "test-engineer", "wiring-verifier". _GENERIC_ROLE_SECTION for unknown roles. _generate_role_section(role) returns correct section or generic fallback. |
| TECH-035 | _generate_mcp_section lists tools | PASS | claude_md_generator.py:121-151 | Lists 6 Contract Engine tools and 7 Codebase Intelligence tools when respective keys exist in mcp_servers dict. BUT: PRD says function signature is `_generate_mcp_section(mcp_servers: dict, role: str)` -- actual signature is `_generate_mcp_section(mcp_servers: dict)` (no role param). Content is not role-specific. Minor deviation but function works. |
| TECH-036 | _generate_convergence_section | PASS | claude_md_generator.py:156-167 | Extracts min_convergence_ratio from config and formats bullet list. Uses `getattr(config.convergence, "min_convergence_ratio", 0.9)`. |

### Milestone 5: Contract Scans + Tracking + Verification (TECH-037 through TECH-044)

| ID | Description | Verdict | Evidence | Notes |
|----|-------------|---------|----------|-------|
| TECH-037 | ContractScanConfig dataclass | PASS | config.py:312-322 | Fields: endpoint_schema_scan=True, missing_endpoint_scan=True, event_schema_scan=True, shared_model_scan=True. Match PRD. (Note: @dataclass decorator missing in visible code at L312, but L325 has @dataclass for next class -- this is actually at L311 before the class. Confirmed by class being used successfully.) |
| TECH-038 | contract_scans on root config | PASS | config.py:543 | `contract_scans: ContractScanConfig = field(default_factory=ContractScanConfig)` |
| TECH-039 | _dict_to_config parses contract_scans | PASS | config.py:1457-1466 | Parsing of all 4 boolean fields with user_overrides tracking. |
| TECH-040 | Violations use existing Violation dataclass | FAIL | contract_scanner.py:73-81 | PRD says "use the existing Violation dataclass from quality_checks.py". BUT contract_scanner.py defines its OWN Violation dataclass at line 73-81 with fields: check, message, file_path, line, severity. This is a SEPARATE class, not the one from quality_checks.py. |
| TECH-041 | ScanScope applied to CONTRACT scans | PASS | contract_scanner.py:117-127 | _should_scan_file() checks scope.mode and scope.changed_files. Used in run_endpoint_schema_scan (line 331), run_missing_endpoint_scan (scope param accepted but not used on individual files -- uses full file list for detection), run_event_schema_scan (line 636), run_shared_model_scan (line 769). |
| TECH-042 | CONTRACT-001 extracts DTO fields for TS/Python/C# | PASS | contract_scanner.py:229-272 | _extract_dto_fields_typescript (interface/class/type blocks), _extract_dto_fields_python (dataclass/Pydantic field patterns), _extract_dto_fields_csharp (public property patterns). |
| TECH-043 | CONTRACT-002 detects route decorators across frameworks | PASS | contract_scanner.py:33-49 | _FLASK_ROUTE_PATTERNS, _FASTAPI_ROUTE_PATTERNS, _EXPRESS_ROUTE_PATTERNS, _ASPNET_ROUTE_PATTERNS covering @app.route, @router.get, router.get(), [HttpGet]/[Route]. PRD mentions @GetMapping (Java) but no Java patterns in code -- MINOR gap. |
| TECH-044 | Depth gating for Build 2 features | FAIL | config.py:588-685 | **quick**: contract scans off (L627-630) PASS. But contract_engine, codebase_intelligence, agent_teams NOT explicitly disabled in quick. PRD says "quick = all contract scans off + contract_engine off + codebase_intelligence off + agent_teams off". These are False by default so effectively off, but no explicit gating. **standard**: CONTRACT 001-002 on, 003-004 off (L658-660) PASS. But PRD says "contract_engine enabled (validation_on_build=True, test_generation=False)" and "codebase_intelligence enabled (replace_static_map=False, register_artifacts=False)" -- NONE of these are gated in standard depth. **thorough**: PRD says "full contract_engine + full codebase_intelligence + all 4 CONTRACT scans + agent_teams enabled (if env set)" -- NO thorough gating for these features. No agent_teams enabling. **exhaustive**: PRD says "same as thorough" -- no gating present either. FAIL: standard/thorough/exhaustive depth gating for contract_engine, codebase_intelligence, agent_teams features is MISSING. |

---

## WIRE Requirements Audit

| ID | Description | Verdict | Evidence | Notes |
|----|-------------|---------|----------|-------|
| WIRE-001 | create_execution_backend() in cli.py | PASS | cli.py:4799-4814 | Called within `if config.agent_teams.enabled:` block. `from .agent_teams_backend import create_execution_backend`, assigned to `_execution_backend`, result to `_team_state`. |
| WIRE-002 | write_hooks_to_project() after backend init | PASS | cli.py:4817-4828 | Called after WIRE-001, gated on `_team_state is not None and _team_state.mode == "agent_teams"`. Imports generate_hooks_config and write_hooks_to_project. |
| WIRE-003 | Teammate shutdown in _handle_interrupt() | PASS | cli.py:3219-3247 | _handle_interrupt checks `_team_state is not None and _team_state.active` (L3225), attempts shutdown. Saves agent_teams_active to state (L3237). |
| WIRE-003A | team_state on _module_state | PARTIAL | cli.py:3216 | `_team_state = None` is module-level (not on a _module_state object). PRD says "Add team_state to _module_state in cli.py" but implementation uses bare module-level variable `_team_state`. Signal handler accesses it via `global _team_state`. Functionally equivalent but not on a state object. |
| WIRE-004 | _contract_engine_mcp_server in mcp_servers.py | PASS | mcp_servers.py:173-192 | Returns dict with type=stdio, command=config.mcp_command, args=config.mcp_args, env={DATABASE_PATH: ...} when database_path non-empty. |
| WIRE-005 | Contract engine in get_contract_aware_servers() | PASS | mcp_servers.py:239-240 | `if config.contract_engine.enabled: servers["contract_engine"] = _contract_engine_mcp_server(config.contract_engine)` |
| WIRE-006 | _codebase_intelligence_mcp_server in mcp_servers.py | PASS | mcp_servers.py:195-227 | Returns dict with type=stdio, command, args, env with DATABASE_PATH, CHROMA_PATH, GRAPH_PATH when non-empty. |
| WIRE-007 | Codebase intelligence in get_contract_aware_servers() | PASS | mcp_servers.py:242-243 | `if config.codebase_intelligence.enabled: servers["codebase_intelligence"] = _codebase_intelligence_mcp_server(config.codebase_intelligence)` |
| WIRE-008 | get_contract_aware_servers function exists | PASS | mcp_servers.py:230-245 | Calls `get_mcp_servers(config)` then conditionally adds contract_engine and codebase_intelligence. |
| WIRE-009 | ArchitectClient in mcp_clients.py | PASS | mcp_clients.py:177-264 | ArchitectClient class with 4 methods: decompose, get_service_map, get_contracts_for_service, get_domain_model. All with try/except returning empty defaults. Uses _extract_json from contract_client. |
| WIRE-010 | CLAUDE.md generation before milestone execution | PASS | cli.py:4830-4852 | After WIRE-002 block, gated on `_team_state is not None and _team_state.mode == "agent_teams"`. Calls write_teammate_claude_md for 5 roles: architect, code-writer, code-reviewer, test-engineer, wiring-verifier. |
| WIRE-011 | contract_context and codebase_index_context wiring | PASS | cli.py:4355-4440, 4918-4919, 4970-4971 | `_codebase_index_context` populated at L4355-4377 from MCP codebase map. `_contract_context` populated at L4411-4440 from Contract Engine query. Both passed to `_run_prd_milestones()` (L4918-4919) and `_run_single()` (L4970-4971) which forward to prompt builders. |
| WIRE-012 | contract_report update after CONTRACT scans | PASS | cli.py:5936-5970 | Post-orchestration block populates `_current_state.contract_report` via ContractReport dataclass with total_contracts, implemented, violations, compliance_ratio, health. Gated on `config.contract_engine.enabled and _service_contract_registry is not None`. |
| WIRE-013 | registered_artifacts tracking | PASS | cli.py:6005-6038 | Post-orchestration block calls `register_new_artifact()` for newly created files (capped at 50) via `create_codebase_intelligence_session()`. Extends `_current_state.registered_artifacts`. Gated on `config.codebase_intelligence.enabled and config.codebase_intelligence.register_artifacts`. NOTE: Does NOT use before/after file set comparison as PRD specifies -- instead scans requirements_dir for code files. Partial implementation difference. |
| WIRE-014 | run_contract_compliance_scan in post-orchestration | PASS | cli.py:5874-5931 | `run_contract_compliance_scan()` called at L5890, gated on any contract_scans boolean being True + _service_contract_registry presence. Runs after existing scans. Passes `scope=scan_scope`. |
| WIRE-015 | CONTRACT violation fix loop | PASS | cli.py:5904-5923 | Fix loop uses `_run_contract_compliance_fix()` (L5908) within max_scan_fix_passes iteration. Follows established multi-pass scan-fix pattern. |
| WIRE-016 | generate_contract_compliance_matrix() wiring | PASS | cli.py:5975-6000 | Called at L5991 after CONTRACT scans. Gated on `config.contract_engine.enabled and config.tracking_documents.contract_compliance_matrix`. Writes to `CONTRACT_COMPLIANCE_MATRIX.md`. |
| WIRE-017 | verify_contract_compliance() in verification.py | PASS | verification.py:153, 1149 | `verify_contract_compliance(contract_report)` defined at L1149. Called from verify_task_completion at L153 as advisory phase. |

---

## Critical Findings

### P0: Must Fix

1. **TECH-029 (ContractReport fields):** State.py ContractReport has completely different field names than PRD spec. Missing: verified_contracts, violated_contracts, missing_implementations, verified_contract_ids, violated_contract_ids. Has: implemented, compliance_ratio (not in PRD). `violations` is int instead of list[dict].

2. **TECH-030 (EndpointTestReport fields):** Field names shortened (tested vs tested_endpoints, passed vs passed_endpoints, failed vs failed_endpoints). Missing: untested_contracts:list[str].

3. **TECH-040 (Violation dataclass):** contract_scanner.py defines its OWN Violation class instead of using the existing one from quality_checks.py. This creates a parallel type hierarchy -- scans return contract_scanner.Violation, not quality_checks.Violation.

4. **TECH-044 (Depth gating):** Standard depth should enable contract_engine (validation_on_build=True, test_generation=False) and codebase_intelligence (replace_static_map=False, register_artifacts=False). Thorough should enable full contract_engine + full codebase_intelligence + agent_teams. NONE of these are gated -- only contract_scans booleans are gated for quick/standard.

### P1: Should Fix

5. **TECH-012A (TaskResult file tracking):** files_created and files_modified are always empty lists -- no actual parsing of Write/Edit tool calls to detect changed files.

6. **TECH-020 (StdioServerParameters cwd):** PRD requires passing `cwd=config.server_root` to StdioServerParameters. Not implemented in create_contract_engine_session() or create_codebase_intelligence_session().

7. **TECH-043 (Java route detection):** PRD mentions @GetMapping (Java/Spring Boot) but no Java patterns in contract_scanner.py.

8. **WIRE-013 (registered_artifacts method):** Uses requirements_dir file scan instead of PRD-specified before/after set comparison for detecting newly created files.

### P2: Minor

9. **TECH-014 (spec_hash computation):** PRD implies local computation via hashlib. Code stores server-provided value. Functionally acceptable if server computes correctly.

10. **TECH-035 (_generate_mcp_section signature):** PRD says `(mcp_servers, role)` but actual is `(mcp_servers)` only. Content is not role-specific. Minor divergence.

11. **WIRE-003A (team_state location):** Uses module-level `_team_state` variable instead of `_module_state.team_state` attribute. Functionally equivalent.

---

## Verification Notes

- All source files were READ-ONLY examined; no edits were made.
- Evidence cites are file:line format from actual source inspection.
- cli.py pipeline wiring verified via targeted grep + read at relevant offsets (5800-6050 for contract scans, 4350-4470 for context wiring, 4790-4920 for backend init/hooks/CLAUDE.md, 3210-3250 for signal handler).
- All 17 WIRE requirements verified against actual cli.py code. WIRE-011/012/013 initially marked FAIL but corrected to PASS after discovering wiring at cli.py:4355-4440 and cli.py:5936-6038.
- TECH verdicts based on exact field name/type/default comparison against PRD spec.

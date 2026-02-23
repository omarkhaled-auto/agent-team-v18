# ARCHITECTURE_REPORT.md — Build 2 Phase 1 Discovery

> **Generated:** 2026-02-23 | **Scope:** Full Build 2 source analysis | **Sections:** 1A–1J

---

## 1A: CLI Pipeline Execution Flow

**Entry point**: `cli.py` — main CLI pipeline

**Key functions:**
- `_build_options()` (cli.py:254): Builds ClaudeAgentOptions with all agents and MCP servers. Gets contract-aware servers via `get_contract_aware_servers(config)` which adds contract_engine and codebase_intelligence MCP servers when enabled.
- `_run_interactive()` (cli.py:412): Main interactive loop. Calls `apply_depth_quality_gating()` before building options.
- `_process_response()` (cli.py:345): Processes streaming SDK responses.

**Execution order:**
1. Parse args, load config via `load_config()` -> returns `tuple[AgentTeamConfig, set[str]]`
2. Detect depth via `detect_depth()`
3. Apply depth gating via `apply_depth_quality_gating(depth, config, user_overrides)`
4. Build options via `_build_options()` which calls `get_contract_aware_servers(config)`
5. Run interactive/single-shot mode

**Config flag gating:**
- `config.contract_engine.enabled` -> adds contract_engine MCP server to options
- `config.codebase_intelligence.enabled` -> adds codebase_intelligence MCP server to options
- `config.agent_teams.enabled` -> selects AgentTeamsBackend vs CLIBackend via `create_execution_backend()`

**`_dict_to_config` function** (config.py:1024):
- Signature: `_dict_to_config(data: dict[str, Any]) -> tuple[AgentTeamConfig, set[str]]`
- Return type: `tuple[AgentTeamConfig, set[str]]` — config + user_overrides set
- Unknown config keys: silently ignored (only known sections are processed)
- Depth gating defaults: applied AFTER config loading via `apply_depth_quality_gating()`
- User overrides tracking: keys in `user_overrides` set use dotted paths like `"contract_engine.enabled"`, `"agent_teams.enabled"`, etc.

**MCP client creation points:**
- `get_contract_aware_servers()` (mcp_servers.py:298) creates MCP server configs
- `create_contract_engine_session()` (mcp_clients.py:43) creates stdio MCP session
- `create_codebase_intelligence_session()` (mcp_clients.py:110) creates stdio MCP session

**Agent Teams backend selection:**
- `create_execution_backend()` (agent_teams_backend.py:720) is the factory function

---

## 1B: MCP Client Architecture

### ContractEngineClient (contract_client.py:197)

**6 methods:**

| Method | MCP Tool | Parameters | Success Return | Failure Default |
|--------|----------|------------|----------------|-----------------|
| `get_contract(contract_id)` | `get_contract` | `{"contract_id": str}` | `ContractInfo` | `None` |
| `validate_endpoint(service_name, method, path, response_body, status_code)` | `validate_endpoint` | `{"service_name", "method", "path", "response_body", "status_code"}` | `ContractValidation` | `ContractValidation(error=str(exc))` |
| `generate_tests(contract_id, framework, include_negative)` | `generate_tests` | `{"contract_id", "framework", "include_negative"}` | `str` (test content) | `""` |
| `check_breaking_changes(contract_id, new_spec)` | `check_breaking_changes` | `{"contract_id", "new_spec"}` | `list[dict]` | `[]` |
| `mark_implemented(contract_id, service_name, evidence_path)` | `mark_implemented` | `{"contract_id", "service_name", "evidence_path"}` | `dict` with marked/total/all_implemented | `{"marked": False}` |
| `get_unimplemented_contracts(service_name)` | `get_unimplemented_contracts` | `{"service_name"?}` | `list[dict]` | `[]` |

### CodebaseIntelligenceClient (codebase_client.py:66)

**7 methods:**

| Method | MCP Tool | Parameters | Success Return | Failure Default |
|--------|----------|------------|----------------|-----------------|
| `find_definition(symbol, language)` | `find_definition` | `{"symbol", "language"}` | `DefinitionResult` | `DefinitionResult()` |
| `find_callers(symbol, max_results)` | `find_callers` | `{"symbol", "max_results"}` | `list` | `[]` |
| `find_dependencies(file_path)` | `find_dependencies` | `{"file_path"}` | `DependencyResult` | `DependencyResult()` |
| `search_semantic(query, language, service_name, n_results)` | `search_semantic` | `{"query", ...}` | `list` | `[]` |
| `get_service_interface(service_name)` | `get_service_interface` | `{"service_name"}` | `dict` | `{}` |
| `check_dead_code(service_name)` | `check_dead_code` | `{"service_name"?}` | `list` | `[]` |
| `register_artifact(file_path, service_name, timeout_ms)` | `register_artifact` | `{"file_path", "service_name"}` | `ArtifactResult` | `ArtifactResult()` |

### Session Management (mcp_clients.py)

**Pattern**: Async context managers `create_contract_engine_session()` and `create_codebase_intelligence_session()`

**Session lifecycle:**
1. Lazy import MCP SDK (`from mcp import ClientSession, StdioServerParameters`)
2. Build `StdioServerParameters` with command, args, env, cwd
3. `async with stdio_client(server_params) as (read_stream, write_stream)`
4. `async with ClientSession(read_stream, write_stream) as session`
5. **CRITICAL**: `await asyncio.wait_for(session.initialize(), timeout=startup_timeout)` called before yield
6. Yield session to caller
7. Context manager teardown handles cleanup

**Timeout handling**: `startup_timeout_ms / 1000.0` seconds for `session.initialize()`

**Failure on server start**: If `stdio_client` or `session.initialize()` raises `TimeoutError`, `ConnectionError`, `ProcessLookupError`, or `OSError`, wraps in `MCPConnectionError`

**MCPConnectionError** (mcp_clients.py:30): Custom exception wrapping transport errors. Raised when connection fails during initialization.

### Retry Logic (contract_client.py:104)

**`_call_with_retry()`**:
- 3 retries (`_MAX_RETRIES = 3`)
- Backoff: `[1, 2, 4]` seconds
- Transient errors (retry): `OSError`, `TimeoutError`, `ConnectionError`
- Non-transient errors (fail immediately): `TypeError`, `ValueError`
- Other errors (e.g., `RuntimeError` from MCP isError): treated as transient, retried
- Final behavior: raises the last error after all retries exhausted

**Note**: `register_artifact` does NOT use `_call_with_retry` — single attempt with direct `asyncio.wait_for` timeout (per INT-005).

### Environment Security (SEC-001)
Both session managers only pass specific env vars to MCP subprocess — never spread `os.environ`.

---

## 1C: Contract Engine Integration Points

**Client instantiation**: Via `create_contract_engine_session()` in mcp_clients.py — called when `config.contract_engine.enabled` is True

**ServiceContractRegistry** (contracts.py:681):
- `load_from_mcp(client)`: Calls `client.get_unimplemented_contracts("")` then `client.get_contract(cid)` for each
- `load_from_local(path)`: Reads CONTRACTS.json cache
- `save_local_cache(path)`: Writes CONTRACTS.json, **strips securitySchemes** (SEC-003)
- Fallback: `load_from_mcp` catches exceptions and falls back to `load_from_local(cache_path)` when `cache_path` provided

**validate_endpoint**: Called via `ServiceContractRegistry.validate_endpoint()` which delegates to `client.validate_endpoint()`

**CONTRACT scans**: Triggered in post-orchestration scan pipeline via `run_contract_compliance_scan()` (contract_scanner.py:822). Gated by `config.contract_scans` individual flags.

**Contract compliance E2E**: Uses `E2E_CONTRACT_COMPLIANCE_PROMPT` from e2e_testing.py, triggered after standard E2E tests

**Fallback chain**:
- MCP available -> live validation
- MCP fails -> `ServiceContractRegistry` falls back to local cache
- No cache -> empty registry, pipeline continues

---

## 1D: Codebase Intelligence Integration Points

**Client instantiation**: Via `create_codebase_intelligence_session()` when `config.codebase_intelligence.enabled`

**MCP-backed codebase map**: When `replace_static_map=True`, calls `generate_codebase_map_from_mcp()` (codebase_map.py) which uses `get_service_interface`, `find_dependencies`, and `search_semantic`

**Artifact registration**: When `register_artifacts=True`, calls `client.register_artifact()` after new file creation during builds

**Semantic search**: Called during context assembly with architecture query, formatted as `codebase_index_context` with CODEBASE INTELLIGENCE CONTEXT delimiters

**Fallback chain**:
- MCP available -> live semantic search/dependency analysis
- MCP unavailable -> fallback to static `generate_codebase_map()`
- Empty string context on failure (not error message, not crash)

---

## 1E: Agent Teams Backend

### ExecutionBackend Protocol (agent_teams_backend.py:92)

Required methods:
- `initialize() -> TeamState`
- `execute_wave(wave: ExecutionWave) -> WaveResult`
- `execute_task(task: ScheduledTask) -> TaskResult`
- `send_context(context: str) -> bool`
- `shutdown() -> None`
- `supports_peer_messaging() -> bool`
- `supports_self_claiming() -> bool`

### CLIBackend (agent_teams_backend.py:136)
- Sequential task execution via subprocess
- `supports_peer_messaging()` -> False
- `supports_self_claiming()` -> False

### AgentTeamsBackend (agent_teams_backend.py:264)
- Parallel task execution via asyncio.gather
- Wave and task timeouts from config
- `supports_peer_messaging()` -> True
- `supports_self_claiming()` -> True
- **Note**: Contains TODO placeholders — actual Agent Teams SDK integration not yet implemented

### create_execution_backend() Factory (agent_teams_backend.py:720)

Decision tree:
1. `agent_teams.enabled=False` -> CLIBackend
2. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS != "1"` -> CLIBackend with warning (regardless of fallback_to_cli)
3. Env set but claude CLI unavailable + `fallback_to_cli=True` -> CLIBackend with warning
4. Env set but claude CLI unavailable + `fallback_to_cli=False` -> RuntimeError
5. Platform/display-mode incompatible + `fallback_to_cli=True` -> CLIBackend with warning
6. Platform/display-mode incompatible + `fallback_to_cli=False` -> RuntimeError
7. All conditions met -> AgentTeamsBackend

**IMPORTANT FINDING**: Branch 2 returns CLIBackend WITHOUT checking `fallback_to_cli`. When env var is not set but `enabled=True` and `fallback_to_cli=False`, it STILL returns CLIBackend instead of raising RuntimeError. This differs from the verification spec which expects RuntimeError.

### detect_agent_teams_available() (agent_teams_backend.py:817)
Checks: env var == "1", claude CLI responds, platform compatibility for display mode.

---

## 1F: Hooks System

### hooks_manager.py

**4 hook types:**

1. **TaskCompleted** (agent hook): Reads REQUIREMENTS.md, verifies `[x]` items are implemented. Timeout: 120s.
2. **TeammateIdle** (command hook): Script `.claude/hooks/teammate-idle-check.sh` — uses `claude -p` to check for pending unblocked tasks. Exit 2 blocks transition, exit 0 allows.
3. **Stop** (command hook): Script `.claude/hooks/quality-gate.sh` — reads HookInput JSON, checks REQUIREMENTS.md completion ratio >= 80%. Exit 2 blocks stop.
4. **PostToolUse** (command hook, async): Script `.claude/hooks/track-file-change.sh` — logs Write/Edit tool invocations to file-changes.log. Matcher: `"Write|Edit"`.

### generate_hooks_config() (hooks_manager.py:221)
Assembles all 4 hooks into a HookConfig.

### write_hooks_to_project() (hooks_manager.py:273)
- Creates `.claude/` and `.claude/hooks/` directories
- Merges hooks into `.claude/settings.local.json`
- Writes scripts to `.claude/hooks/<filename>`
- Attempts `chmod 0o755` on scripts (gracefully ignored on Windows)

---

## 1G: CLAUDE.md Generation

### claude_md_generator.py

**5 roles**: `architect`, `code-writer`, `code-reviewer`, `test-engineer`, `wiring-verifier`

**Sections generated:**
1. Role section (`_generate_role_section`) — role-specific instructions
2. Service context (if service_name provided)
3. Dependencies section
4. Tech stack section
5. Codebase context section
6. MCP tools section (`_generate_mcp_section`) — lists Contract Engine and Codebase Intelligence tools
7. Convergence mandates section — includes `min_convergence_ratio` from config
8. Quality standards section
9. Contract section (`_generate_contract_section`) — lists active contracts with truncation

**contract_limit** (default 100): Contracts beyond limit are truncated with suffix: `"... and {overflow} more. Use Contract Engine get_contract(contract_id) MCP tool to fetch additional contracts on demand."`

**Idempotent writes** (write_teammate_claude_md):
- Markers: `<!-- AGENT-TEAMS:BEGIN -->` and `<!-- AGENT-TEAMS:END -->`
- If markers exist: replace content between them
- If no markers: append after existing content
- Preserves content outside the delimited block

**Role-specific content:**
- **architect**: Design architecture, file ownership maps, query Contract Engine for existing contracts, query Codebase Intelligence, generate SVC-xxx contract stubs. NO code writing, NO marking `[x]`.
- **code-writer**: Implement requirements, ZERO MOCK DATA POLICY, validate endpoints against contracts, register artifacts with Codebase Intelligence. NO marking `[x]`.
- **code-reviewer**: Adversarial review, contract compliance verification, field name accuracy, detect mock data. CAN mark `[x]`. CONTRACT violations are blocking.
- **test-engineer**: Comprehensive tests, use Contract Engine generate_tests, contract conformance tests.
- **wiring-verifier**: Cross-file verification, use find_dependencies for import tracing, use check_dead_code for unused exports, contract endpoint verification.

---

## 1H: CONTRACT Scans

### contract_scanner.py

**CONTRACT-001** (Endpoint Schema Scan, `run_endpoint_schema_scan`):
- Detects: Response DTO field mismatches vs contracted fields
- Pattern: Extracts expected fields from OpenAPI response schemas, extracts actual DTO fields from code (TS/Py/C# extractors), checks for missing fields
- Severity: `error`
- Depth gating: enabled at standard+ (disabled at quick)
- Case variations: skipped (handled by CONTRACT-004)

**CONTRACT-002** (Missing Endpoint Scan, `run_missing_endpoint_scan`):
- Detects: Contracted endpoints without route handlers
- Pattern: Extracts all route definitions (Flask, FastAPI, Express, ASP.NET patterns), normalizes paths, checks each contracted endpoint has a match
- Severity: `error`
- Depth gating: enabled at standard+ (disabled at quick)

**CONTRACT-003** (Event Schema Scan, `run_event_schema_scan`):
- Detects: Event payload field mismatches vs AsyncAPI schemas
- Pattern: Extracts event channels from AsyncAPI specs, searches for emit/publish/dispatch calls, checks payload fields
- Severity: `warning`
- Depth gating: enabled at thorough+ (disabled at quick, standard)

**CONTRACT-004** (Shared Model Scan, `run_shared_model_scan`):
- Detects: Naming drift across language boundaries (camelCase/snake_case/PascalCase)
- Pattern: Extracts schema fields from contract specs, checks against TS/Py/C# code files with case-variant matching
- Severity: `warning`
- Depth gating: enabled at thorough+ (disabled at quick, standard)

**Orchestrator**: `run_contract_compliance_scan()` (contract_scanner.py:822) runs all 4 scans, each crash-isolated. Respects `config.contract_scans` flags. Caps at `_MAX_VIOLATIONS = 100`.

---

## 1I: Config and Depth Gating

### Four new Build 2 config sections:

1. **AgentTeamsConfig** (config.py:488): `enabled=False`, `fallback_to_cli=True`, `contract_limit=100`, timeouts, display mode
2. **ContractEngineConfig** (config.py:509): `enabled=False`, MCP command/args, `validation_on_build=True`, `test_generation=True`, timeouts
3. **CodebaseIntelligenceConfig** (config.py:527): `enabled=False`, MCP command/args, `replace_static_map=True`, `register_artifacts=True`, timeouts
4. **ContractScanConfig** (config.py:311): All 4 scans default `True`

### Complete Depth Gating Table

| Feature | quick | standard | thorough | exhaustive |
|---------|-------|----------|----------|------------|
| `agent_teams.enabled` | False | (unchanged=False) | True if env var set | True if env var set |
| `contract_engine.enabled` | False | True | True | True |
| `contract_engine.validation_on_build` | n/a | True | (unchanged=True) | (unchanged=True) |
| `contract_engine.test_generation` | n/a | False | True | True |
| `codebase_intelligence.enabled` | False | True | True | True |
| `codebase_intelligence.replace_static_map` | n/a | False | True | True |
| `codebase_intelligence.register_artifacts` | n/a | False | True | True |
| `contract_scans.endpoint_schema_scan` | False | (unchanged=True) | (unchanged=True) | (unchanged=True) |
| `contract_scans.missing_endpoint_scan` | False | (unchanged=True) | (unchanged=True) | (unchanged=True) |
| `contract_scans.event_schema_scan` | False | False | (unchanged=True) | (unchanged=True) |
| `contract_scans.shared_model_scan` | False | False | (unchanged=True) | (unchanged=True) |

### `_dict_to_config` return type
`tuple[AgentTeamConfig, set[str]]` — second element is user_overrides set

### User override precedence
`apply_depth_quality_gating()` uses `_gate()` helper which checks `if key not in overrides` before setting. User-set values ALWAYS take precedence over depth defaults.

### User overrides tracked for Build 2 sections
- `agent_teams.enabled`
- `contract_engine.enabled`, `contract_engine.validation_on_build`, `contract_engine.test_generation`
- `codebase_intelligence.enabled`, `codebase_intelligence.replace_static_map`, `codebase_intelligence.register_artifacts`
- `contract_scans.*` (all keys in section)

---

## 1J: Test Infrastructure

### Test files (82 files)

Key Build 2 test files:

| File | Size | Coverage Area |
|------|------|---------------|
| `test_build2_backward_compat.py` | 46,519 bytes | Backward compatibility tests |
| `test_build2_config.py` | 17,486 bytes | Build 2 config tests |
| `test_build2_wiring.py` | 21,684 bytes | Build 2 wiring tests |
| `test_contract_client.py` | 35,893 bytes | ContractEngineClient tests |
| `test_codebase_client.py` | 43,659 bytes | CodebaseIntelligenceClient tests |
| `test_contract_scanner.py` | 35,223 bytes | CONTRACT scan tests |
| `test_contracts.py` | 21,600 bytes | ContractRegistry tests |
| `test_agent_teams_backend.py` | 23,855 bytes | Agent Teams backend tests |
| `test_hooks_manager.py` | 13,034 bytes | Hooks tests |
| `test_claude_md_generator.py` | 13,092 bytes | CLAUDE.md generation tests |
| `test_depth_gating.py` | 10,777 bytes | Depth gating tests |
| `test_config.py` | 58,443 bytes | Main config tests |

### Conftest fixtures (conftest.py)
- `default_config` — default AgentTeamConfig
- `config_with_disabled_agents` — planner/researcher/debugger disabled
- `config_with_disabled_mcp` — all MCP servers disabled
- `config_yaml_file` — valid YAML config on disk
- `env_with_api_keys` — sets ANTHROPIC + FIRECRAWL env vars
- `full_config_with_new_features` — codebase_map + scheduler + verification enabled
- `config_with_milestones` — milestone orchestration enabled
- `milestone_project_structure` — temp directory with milestone REQUIREMENTS.md files

### MCP session mock patterns
Tests use `unittest.mock.AsyncMock` to mock `session.call_tool()` and `session.initialize()`. MCP sessions are typically mocked at the client level by passing a mock session to `ContractEngineClient(session)`.

### Skipped tests
Tests marked `@pytest.mark.e2e` are skipped unless `--run-e2e` flag is passed.

### integration_upgrades_proof/
Contains integration test proofs for Build 2 upgrade features.

---

## Critical Findings

### FINDING 1: session.initialize() IS called
Both `create_contract_engine_session()` (mcp_clients.py:94) and `create_codebase_intelligence_session()` (mcp_clients.py:174) correctly call `session.initialize()` before yielding. No critical bug here.

### FINDING 2: Agent Teams Backend Branch 2 Behavior
`create_execution_backend()` at branch 2 (env var not set) always returns CLIBackend with a warning, REGARDLESS of `fallback_to_cli` setting. The spec expects RuntimeError when `fallback_to_cli=False` but the code does not check this. Need to verify if this is intentional or a bug.

### FINDING 3: All Build 2 sections default to disabled
`AgentTeamsConfig.enabled=False`, `ContractEngineConfig.enabled=False`, `CodebaseIntelligenceConfig.enabled=False`, `ContractScanConfig` all scans default True (but gated by depth). This ensures backward compatibility when config does not mention these sections.

### FINDING 4: register_artifact has no retry
Unlike other codebase_client methods that use `_call_with_retry`, `register_artifact` does a single attempt with `asyncio.wait_for` timeout. This is intentional per INT-005.

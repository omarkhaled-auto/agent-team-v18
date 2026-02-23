# Phase 4: Wiring Verification Report

**Date:** 2026-02-23
**Project:** agent-team-v15
**Scope:** End-to-end wiring between MCP servers, clients, sessions, config, hooks, and CLAUDE.md

---

## Chain 1: MCP Server -> Session -> Client -> Registry

**Goal:** `config.contract_engine.enabled` -> `get_contract_aware_servers` adds `"contract_engine"` key -> `create_contract_engine_session` gets `ContractEngineConfig` -> session -> `ContractEngineClient(session)` -> `ServiceContractRegistry.load_from_mcp(client)`

### Link 1.1: Config flag -> get_contract_aware_servers

- **File:** `src/agent_team_v15/config.py:588`
  - `AgentTeamConfig.contract_engine: ContractEngineConfig` -- field exists, type is `ContractEngineConfig`
  - `ContractEngineConfig.enabled: bool = False` (line 515)
- **File:** `src/agent_team_v15/mcp_servers.py:298-313`
  - `get_contract_aware_servers(config)` checks `config.contract_engine.enabled` (line 307)
  - When True, adds `servers["contract_engine"] = _contract_engine_mcp_server(config.contract_engine)` (line 308)
  - `_contract_engine_mcp_server` accepts `ContractEngineConfig` (line 241) -- type matches
- **Result:** PASS

### Link 1.2: get_contract_aware_servers called from _build_options

- **File:** `src/agent_team_v15/cli.py:275`
  - `mcp_servers = get_contract_aware_servers(config)` inside `_build_options()`
  - The resulting dict is passed to `ClaudeAgentOptions` (line 329)
- **Result:** PASS

### Link 1.3: create_contract_engine_session receives ContractEngineConfig

- **File:** `src/agent_team_v15/cli.py:4656-4657`
  - `create_contract_engine_session(config.contract_engine)` -- passes `ContractEngineConfig` instance
- **File:** `src/agent_team_v15/mcp_clients.py:43-45`
  - `create_contract_engine_session(config: "ContractEngineConfig")` -- parameter type matches
  - Uses `config.mcp_command`, `config.mcp_args`, `config.database_path`, `config.server_root`, `config.startup_timeout_ms` -- all exist on `ContractEngineConfig` (config.py:516-522)
- **Result:** PASS

### Link 1.4: Session -> ContractEngineClient

- **File:** `src/agent_team_v15/cli.py:4659-4660`
  - `client = ContractEngineClient(session)` -- wraps the MCP `ClientSession`
- **File:** `src/agent_team_v15/contract_client.py:211`
  - `__init__(self, session: Any)` -- accepts any session object, stores as `self._session`
- **Result:** PASS

### Link 1.5: ContractEngineClient -> ServiceContractRegistry.load_from_mcp

- **File:** `src/agent_team_v15/cli.py:4661-4663`
  - `await _service_contract_registry.load_from_mcp(client, cache_path=_mcp_cache_path)`
- **File:** `src/agent_team_v15/contracts.py:706-708`
  - `load_from_mcp(self, client: Any, *, cache_path: Path | None = None)`
  - Calls `client.get_unimplemented_contracts("")` (line 718) -- method exists on `ContractEngineClient` (contract_client.py:379), accepts `str | None`
  - Calls `client.get_contract(cid)` (line 723) -- method exists on `ContractEngineClient` (contract_client.py:216), returns `ContractInfo | None`
  - Accesses `info.type`, `info.service_name`, `info.version`, `info.spec_hash`, `info.spec` (lines 726-733) -- all fields exist on `ContractInfo` dataclass (contract_client.py:46-56)
- **Result:** PASS

### Link 1.6: Fallback chain (MCP -> local cache -> empty)

- **File:** `src/agent_team_v15/cli.py:4648-4697`
  - Primary: MCP session + `load_from_mcp(client, cache_path=...)` (lines 4656-4664)
  - Inside `load_from_mcp`: on exception, falls back to `self.load_from_local(cache_path)` (contracts.py:738-740)
  - CLI-level fallback: except block (lines 4681-4697) catches all exceptions, creates fresh `ServiceContractRegistry()`, tries `load_from_local()` on the cache file
  - Final fallback: if local cache does not exist, `load_from_local` returns silently, registry stays empty (contracts.py:749-750)
- **Result:** PASS -- triple-layer fallback verified

### Chain 1 Overall: **PASS**

---

## Chain 2: MCP Server -> Session -> Client -> Codebase Map

**Goal:** `config.codebase_intelligence.enabled` -> `get_contract_aware_servers` adds `"codebase_intelligence"` key -> `create_codebase_intelligence_session` -> session -> `CodebaseIntelligenceClient(session)` -> `generate_codebase_map_from_mcp(client)`

### Link 2.1: Config flag -> get_contract_aware_servers

- **File:** `src/agent_team_v15/config.py:589`
  - `AgentTeamConfig.codebase_intelligence: CodebaseIntelligenceConfig` -- field exists
  - `CodebaseIntelligenceConfig.enabled: bool = False` (line 534)
- **File:** `src/agent_team_v15/mcp_servers.py:310-311`
  - Checks `config.codebase_intelligence.enabled`, adds `servers["codebase_intelligence"]`
  - `_codebase_intelligence_mcp_server(config: CodebaseIntelligenceConfig)` (line 263) -- type matches
- **Result:** PASS

### Link 2.2: create_codebase_intelligence_session receives CodebaseIntelligenceConfig

- **File:** `src/agent_team_v15/cli.py:4603-4604`
  - `create_codebase_intelligence_session(config.codebase_intelligence)` -- passes `CodebaseIntelligenceConfig`
- **File:** `src/agent_team_v15/mcp_clients.py:110-112`
  - `create_codebase_intelligence_session(config: "CodebaseIntelligenceConfig")` -- type matches
  - Uses `config.mcp_command`, `config.mcp_args`, `config.database_path`, `config.chroma_path`, `config.graph_path`, `config.server_root`, `config.startup_timeout_ms` -- all exist on `CodebaseIntelligenceConfig` (config.py:534-544)
- **Result:** PASS

### Link 2.3: Session -> CodebaseIntelligenceClient -> generate_codebase_map_from_mcp

- **File:** `src/agent_team_v15/cli.py:4606-4608`
  - `client = CodebaseIntelligenceClient(session)` then `await generate_codebase_map_from_mcp(client)`
- **File:** `src/agent_team_v15/codebase_client.py:80`
  - `__init__(self, session: Any)` -- accepts any session
- **File:** `src/agent_team_v15/codebase_map.py:969-970`
  - `generate_codebase_map_from_mcp(client: "Any")` -- calls `client.search_semantic(...)`, `client.get_service_interface(...)`, `client.check_dead_code(...)` (lines 987-991)
  - All three methods exist on `CodebaseIntelligenceClient` (codebase_client.py:85, 214, 239)
- **Result:** PASS

### Link 2.4: Fallback chain (MCP -> static map -> empty)

- **File:** `src/agent_team_v15/cli.py:4591-4636`
  - Primary: MCP path when `config.codebase_intelligence.enabled` and `replace_static_map` (lines 4594-4614)
  - Fallback: static `generate_codebase_map()` when `_used_mcp_map` is False (lines 4620-4633)
  - Final: if static map also fails, prints warning, `codebase_map_summary` stays `None` (lines 4634-4636)
- **Result:** PASS -- dual fallback verified

### Link 2.5: Post-orchestration artifact registration

- **File:** `src/agent_team_v15/cli.py:6305-6338`
  - Guards on `config.codebase_intelligence.enabled` and `config.codebase_intelligence.register_artifacts` (lines 6306-6307)
  - Creates session via `create_codebase_intelligence_session(config.codebase_intelligence)` (line 6322-6323)
  - Creates `CodebaseIntelligenceClient(session)` (line 6326)
  - Calls `register_new_artifact(client, fp)` for each file (line 6329)
  - `register_new_artifact` (codebase_map.py:1040) delegates to `client.register_artifact(file_path, service_name)` -- method exists (codebase_client.py:267)
- **Result:** PASS

### Chain 2 Overall: **PASS**

---

## Chain 3: Config -> Depth Gating -> MCP Servers -> Allowed Tools

**Goal:** `apply_depth_quality_gating` sets config flags -> `get_contract_aware_servers` reads flags -> `recompute_allowed_tools` adds tool names based on servers present

### Link 3.1: apply_depth_quality_gating sets config flags

- **File:** `src/agent_team_v15/config.py:635-760`
  - **quick** depth: disables `contract_engine.enabled`, `codebase_intelligence.enabled`, `agent_teams.enabled` (lines 700-702)
  - **standard** depth: enables `contract_engine.enabled=True`, `codebase_intelligence.enabled=True` with reduced features (lines 713-718)
  - **thorough** depth: full contract_engine and codebase_intelligence; agent_teams conditional on env var (lines 732-739)
  - **exhaustive** depth: same as thorough but with higher limits (lines 757-759)
- **File:** `src/agent_team_v15/cli.py:431`
  - `apply_depth_quality_gating(depth_override or "standard", config, user_overrides)` -- called before any MCP usage
- **Result:** PASS

### Link 3.2: get_contract_aware_servers reads enabled flags

- **File:** `src/agent_team_v15/mcp_servers.py:298-313`
  - `get_contract_aware_servers` builds servers dict from `get_mcp_servers(config)` base
  - Adds `contract_engine` only if `config.contract_engine.enabled` is True (line 307)
  - Adds `codebase_intelligence` only if `config.codebase_intelligence.enabled` is True (line 310)
- **Result:** PASS

### Link 3.3: recompute_allowed_tools adds tool names based on servers

- **File:** `src/agent_team_v15/mcp_servers.py:141-163`
  - `recompute_allowed_tools(base_tools, servers)` adds:
    - `get_research_tools(servers)` for `"firecrawl"` and `"context7"` keys (lines 85-102)
    - `get_orchestrator_st_tool_name()` for `"sequential_thinking"` key (line 160)
    - `get_playwright_tools()` for `"playwright"` key (line 162)
  - **OBSERVATION:** Does NOT add any tool names for `"contract_engine"` or `"codebase_intelligence"` server keys
- **File:** `src/agent_team_v15/cli.py:314`
  - `allowed_tools = recompute_allowed_tools(_BASE_TOOLS, mcp_servers)` -- called in `_build_options`
- **Analysis:** The `allowed_tools` list omits Contract Engine and Codebase Intelligence tool names. Since these are MCP servers injected into `ClaudeAgentOptions.mcp_servers`, the SDK discovers their tools dynamically. However, if the SDK's `allowed_tools` filtering is strict (whitelist-only), these tools would be blocked. This is a **potential issue** depending on SDK behavior. If the SDK treats `allowed_tools` as a whitelist for built-in tools only (not MCP tools), this is fine. If it blocks all unlisted tools including MCP tools, this is broken.
- **Result:** **WARN** -- Contract Engine and Codebase Intelligence MCP tool names are not added to `allowed_tools`; relies on SDK not filtering MCP tools via this list

### Link 3.4: Tool name consistency between mcp_servers.py and claude_md_generator.py

This checks whether the tool names documented in CLAUDE.md match the actual MCP tool names the servers expose.

**mcp_servers.py tool names (used for SDK allowed_tools):**
- Firecrawl: `mcp__firecrawl__firecrawl_search`, `mcp__firecrawl__firecrawl_scrape`, `mcp__firecrawl__firecrawl_map`, `mcp__firecrawl__firecrawl_extract`, `mcp__firecrawl__firecrawl_agent`, `mcp__firecrawl__firecrawl_agent_status` (lines 89-96)
- Context7: `mcp__context7__resolve-library-id`, `mcp__context7__query-docs` (lines 98-101)
- Sequential Thinking: `mcp__sequential-thinking__sequentialthinking` (line 82)
- Playwright: `mcp__playwright__browser_navigate`, etc. (lines 114-137)
- Contract Engine: **NOT listed** in `recompute_allowed_tools`
- Codebase Intelligence: **NOT listed** in `recompute_allowed_tools`

**claude_md_generator.py tool names (documented for agents in CLAUDE.md):**
- Contract Engine tools (lines 101-108): `get_contract`, `validate_endpoint`, `generate_tests`, `check_breaking_changes`, `mark_implemented`, `get_unimplemented_contracts`
- Codebase Intelligence tools (lines 110-118): `find_definition`, `find_callers`, `find_dependencies`, `search_semantic`, `get_service_interface`, `check_dead_code`, `register_artifact`

**Analysis:** The tool names in `claude_md_generator.py` are the **bare MCP tool names** (e.g., `get_contract`), not the SDK-prefixed names (which would be e.g., `mcp__contract_engine__get_contract`). This is intentional -- the CLAUDE.md documents the tool names as the agent would call them via MCP (bare names), while `recompute_allowed_tools` uses SDK-prefixed names. The contract engine client directly calls `session.call_tool("get_contract", ...)` using bare names (contract_client.py:224), which is correct for direct MCP session usage.

The bare tool names in `claude_md_generator.py` match 1:1 with the tool names used in `ContractEngineClient` methods:
| CLAUDE.md tool name | ContractEngineClient method call |
|---|---|
| `get_contract` | `_call_with_retry(session, "get_contract", ...)` (line 224) |
| `validate_endpoint` | `_call_with_retry(session, "validate_endpoint", ...)` (line 261) |
| `generate_tests` | `_call_with_retry(session, "generate_tests", ...)` (line 300) |
| `check_breaking_changes` | `_call_with_retry(session, "check_breaking_changes", ...)` (line 328) |
| `mark_implemented` | `_call_with_retry(session, "mark_implemented", ...)` (line 358) |
| `get_unimplemented_contracts` | `_call_with_retry(session, "get_unimplemented_contracts", ...)` (line 393) |

The bare tool names in `claude_md_generator.py` match 1:1 with the tool names used in `CodebaseIntelligenceClient` methods:
| CLAUDE.md tool name | CodebaseIntelligenceClient method call |
|---|---|
| `find_definition` | `_call_with_retry(session, "find_definition", ...)` (line 99) |
| `find_callers` | `_call_with_retry(session, "find_callers", ...)` (line 133) |
| `find_dependencies` | `_call_with_retry(session, "find_dependencies", ...)` (line 157) |
| `search_semantic` | `_call_with_retry(session, "search_semantic", ...)` (line 199) |
| `get_service_interface` | `_call_with_retry(session, "get_service_interface", ...)` (line 222) |
| `check_dead_code` | `_call_with_retry(session, "check_dead_code", ...)` (line 250) |
| `register_artifact` | `session.call_tool("register_artifact", ...)` (line 283) |

- **Result:** PASS -- tool names are consistent between documentation and client implementations

### Chain 3 Overall: **PASS with WARNING**
- Warning: `recompute_allowed_tools` does not include Contract Engine or Codebase Intelligence tool names. This is benign if the SDK does not filter MCP-discovered tools through the `allowed_tools` list, but could be a problem if it does.

---

## Chain 4: Config -> Backend Selection -> Execution

**Goal:** `config.agent_teams` -> `create_execution_backend` reads config + env -> CLIBackend or AgentTeamsBackend

### Link 4.1: Config access

- **File:** `src/agent_team_v15/config.py:587`
  - `AgentTeamConfig.agent_teams: AgentTeamsConfig` -- field exists
- **File:** `src/agent_team_v15/config.py:488-505`
  - `AgentTeamsConfig` has `enabled`, `fallback_to_cli`, `max_teammates`, `teammate_model`, `teammate_display_mode`, `wave_timeout_seconds`, `task_timeout_seconds` -- all used by backend

### Link 4.2: create_execution_backend called from main()

- **File:** `src/agent_team_v15/cli.py:5037-5040`
  - Guards on `config.agent_teams.enabled` (line 5037)
  - `_execution_backend = create_execution_backend(config)` (line 5040)

### Link 4.3: Factory decision tree

- **File:** `src/agent_team_v15/agent_teams_backend.py:720-809`
  - Branch 1: `not at_cfg.enabled` -> `CLIBackend(config)` (line 756)
  - Branch 2: env var `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS != "1"` -> `CLIBackend(config)` (line 766)
  - Branch 3: CLI not available + `fallback_to_cli=True` -> `CLIBackend(config)` (line 777)
  - Branch 4: CLI not available + `fallback_to_cli=False` -> `raise RuntimeError` (line 779-783)
  - Branch 5: Display mode incompatible -> `CLIBackend` or `RuntimeError` (lines 786-802)
  - Branch 6: All conditions met -> `AgentTeamsBackend(config)` (line 809)
  - `at_cfg = config.agent_teams` (line 751) -- reads `AgentTeamsConfig` correctly

### Link 4.4: Fallback chain

- `AgentTeamsBackend` -> `CLIBackend` (when CLI missing + `fallback_to_cli=True`)
- `CLIBackend` is always constructible (no external dependencies)
- `RuntimeError` only when `fallback_to_cli=False` and conditions unmet
- **File:** `src/agent_team_v15/cli.py:5049-5052` -- Exception handler catches `RuntimeError` and falls back to `_team_state = None`

### Chain 4 Overall: **PASS**

---

## Chain 5: Config -> Hooks -> Project Files

**Goal:** `config` -> `generate_hooks_config` -> `HookConfig` -> `write_hooks_to_project` -> `.claude/settings.local.json` + `.claude/hooks/`

### Link 5.1: generate_hooks_config called from main()

- **File:** `src/agent_team_v15/cli.py:5054-5063`
  - Guards on `_team_state is not None and _team_state.mode == "agent_teams"` (line 5055)
  - `_hooks_config = generate_hooks_config(config=config, project_dir=Path(cwd), requirements_path=...)` (lines 5058-5061)

### Link 5.2: generate_hooks_config signature match

- **File:** `src/agent_team_v15/hooks_manager.py:221-226`
  - `generate_hooks_config(config: AgentTeamConfig, project_dir: Path, requirements_path: Path | None = None)` -> `HookConfig`
  - Parameters match: `config` is `AgentTeamConfig`, `project_dir` is `Path(cwd)`, `requirements_path` is `Path(...)`

### Link 5.3: HookConfig -> write_hooks_to_project

- **File:** `src/agent_team_v15/cli.py:5063`
  - `_hooks_path = write_hooks_to_project(_hooks_config, Path(cwd))`
- **File:** `src/agent_team_v15/hooks_manager.py:273`
  - `write_hooks_to_project(hook_config: HookConfig, project_dir: Path) -> Path`
  - Creates `.claude/` and `.claude/hooks/` directories (lines 283-285)
  - Writes/merges `settings.local.json` with `hook_config.hooks` (lines 287-306)
  - Writes each script from `hook_config.scripts` to `.claude/hooks/` (lines 310-318)

### Link 5.4: Generated hooks content

- `HookConfig.hooks` contains 4 event types: `TaskCompleted`, `TeammateIdle`, `Stop`, `PostToolUse` (lines 242-258)
- `HookConfig.scripts` contains 3 shell scripts: `teammate-idle-check.sh`, `quality-gate.sh`, `track-file-change.sh` (lines 248-258)
- Scripts reference paths relative to `.claude/hooks/` which matches the write location

### Chain 5 Overall: **PASS**

---

## Chain 6: Config -> CLAUDE.md -> MCP Tools Documentation

**Goal:** `config` + `mcp_servers` -> `generate_claude_md` -> role sections + MCP tools section + convergence + contracts

### Link 6.1: write_teammate_claude_md called from main()

- **File:** `src/agent_team_v15/cli.py:5070-5087`
  - `write_teammate_claude_md(role=_role, config=config, mcp_servers=mcp_servers, project_dir=Path(cwd), contracts=_claude_contracts)` (lines 5081-5087)

### Link 6.2: **BROKEN LINK -- `mcp_servers` variable undefined in scope**

- **File:** `src/agent_team_v15/cli.py:5084`
  - `mcp_servers=mcp_servers` -- this references a variable `mcp_servers` that is NOT defined anywhere in the `main()` function scope
  - The only `mcp_servers = ...` assignment is at line 275 inside `_build_options()`, which is a local variable in that function
  - There is no module-level `mcp_servers` variable (confirmed by grep for `^mcp_servers` -- no matches)
  - **Impact:** When Agent Teams mode is active, `write_teammate_claude_md()` will raise `NameError: name 'mcp_servers' is not defined`
  - **Mitigation:** The call is wrapped in `try/except Exception` (line 5070/5089), so the `NameError` is caught and a warning is printed: `"Agent Teams: CLAUDE.md generation failed: ..."`. The program continues, but no CLAUDE.md files are generated for any teammate role.
  - **Fix:** Add `mcp_servers = get_contract_aware_servers(config)` before line 5069, or pass the servers explicitly

### Link 6.3: generate_claude_md signature (when it would work)

- **File:** `src/agent_team_v15/claude_md_generator.py:216-261`
  - `generate_claude_md(role, config, mcp_servers, contracts=None, ...)` -- accepts `dict[str, Any]` for mcp_servers
  - `_generate_mcp_section(mcp_servers)` checks for `"contract_engine"` and `"codebase_intelligence"` keys (lines 129-130) -- these match the keys added by `get_contract_aware_servers`
  - `_generate_convergence_section(config)` reads `config.convergence.min_convergence_ratio` (line 158) -- field exists
  - `_generate_contract_section(contracts)` reads `contract_id`, `provider_service`, `contract_type`, `version`, `implemented` from dicts (lines 193-198) -- matches `ServiceContract` dataclass fields via `asdict()`

### Link 6.4: Contract data flow to CLAUDE.md

- **File:** `src/agent_team_v15/cli.py:5073-5078`
  - `_claude_contracts = [asdict(c) for c in _service_contract_registry.contracts.values()]`
  - `ServiceContract` (contracts.py:663-678) has fields: `contract_id`, `contract_type`, `provider_service`, `consumer_service`, `version`, `spec_hash`, `spec`, `implemented`, `evidence_path`
  - `_generate_contract_section` (claude_md_generator.py:172-211) reads: `contract_id`/`id`, `provider_service`/`service_name`, `contract_type`/`type`, `version`, `implemented` -- uses fallback `.get()` keys that match `ServiceContract` field names

### Chain 6 Overall: **FAIL**
- **Root cause:** `mcp_servers` variable is undefined in `main()` scope at line 5084
- **Severity:** Medium -- silently caught, CLAUDE.md generation skipped for all roles
- **Suggested fix:** Insert `mcp_servers = get_contract_aware_servers(config)` before the CLAUDE.md generation block

---

## Chain 7: Fallback Chains

### 7.1: Contract Engine Fallback

**MCP live -> local cache -> empty registry**

- **File:** `src/agent_team_v15/cli.py:4648-4697`
  1. **MCP live:** `create_contract_engine_session` -> `ContractEngineClient` -> `ServiceContractRegistry.load_from_mcp(client, cache_path=...)` (lines 4656-4664)
  2. **Inside load_from_mcp (contracts.py:717-740):** On any MCP exception, calls `self.load_from_local(cache_path)` if cache_path provided
  3. **CLI-level fallback (lines 4681-4697):** On any exception (including `MCPConnectionError`, `ImportError`), creates fresh registry and tries `load_from_local()` on cache file
  4. **Final empty:** If no cache file exists, `load_from_local` returns silently (contracts.py:749-750), registry stays empty
- **Result:** PASS -- 3-tier fallback confirmed

### 7.2: Codebase Intelligence Fallback

**MCP live -> static codebase_map -> empty string**

- **File:** `src/agent_team_v15/cli.py:4591-4636`
  1. **MCP live:** When `config.codebase_intelligence.enabled` and `replace_static_map` (lines 4594-4614)
  2. **Static fallback:** When `_used_mcp_map` is False, runs `generate_codebase_map()` (lines 4620-4633)
  3. **Final empty:** If static map also fails, `codebase_map_summary` stays `None` (lines 4634-4636)
- **Result:** PASS

### 7.3: Agent Teams Backend Fallback

**AgentTeamsBackend -> CLIBackend -> RuntimeError**

- **File:** `src/agent_team_v15/agent_teams_backend.py:720-809`
  1. **AgentTeamsBackend:** When all conditions met (enabled, env var, CLI available, display mode compatible)
  2. **CLIBackend:** On any condition failure with `fallback_to_cli=True` (branches 2, 3, 5)
  3. **RuntimeError:** Only when `fallback_to_cli=False` and conditions unmet (branches 4, 5)
- **File:** `src/agent_team_v15/cli.py:5037-5052`
  - Additionally, `main()` wraps the entire backend init in try/except (lines 5049-5052), so even RuntimeError is caught and program continues with `_team_state = None` (standard CLI execution)
- **Result:** PASS

---

## Summary

| Chain | Status | Details |
|-------|--------|---------|
| **1: MCP Server -> Session -> Client -> Registry** | **PASS** | All links verified, types match, fallback chain works |
| **2: MCP Server -> Session -> Client -> Codebase Map** | **PASS** | All links verified, types match, dual fallback works |
| **3: Config -> Depth Gating -> MCP Servers -> Allowed Tools** | **PASS (WARN)** | Depth gating -> servers works; `allowed_tools` omits CE/CI tool names (benign if SDK doesn't filter MCP tools) |
| **4: Config -> Backend Selection -> Execution** | **PASS** | Factory decision tree covers all branches with fallback |
| **5: Config -> Hooks -> Project Files** | **PASS** | All hooks generated and written to correct paths |
| **6: Config -> CLAUDE.md -> MCP Tools Documentation** | **FAIL** | `mcp_servers` variable undefined in `main()` scope (line 5084) |
| **7: Fallback Chains** | **PASS** | All three fallback chains (CE, CI, Agent Teams) verified |

---

## Issues Found

### ISSUE-001: `mcp_servers` undefined in CLAUDE.md generation scope (FAIL)

- **Location:** `src/agent_team_v15/cli.py:5084`
- **Severity:** Medium
- **Impact:** When Agent Teams mode is active, all 5 teammate CLAUDE.md files fail to generate. The `NameError` is silently caught by the surrounding try/except, and a warning is printed.
- **Root Cause:** `mcp_servers` is only defined as a local variable inside `_build_options()` (line 275), not in the `main()` function body where line 5084 runs.
- **Suggested Fix:** Add the following line before the CLAUDE.md generation block:
  ```python
  # Before line 5068:
  mcp_servers = get_contract_aware_servers(config)
  ```

### ISSUE-002: `recompute_allowed_tools` omits CE/CI tool names (WARN)

- **Location:** `src/agent_team_v15/mcp_servers.py:141-163`
- **Severity:** Low
- **Impact:** The orchestrator's `allowed_tools` list does not include Contract Engine or Codebase Intelligence MCP tool names. If the Claude SDK uses `allowed_tools` as a strict whitelist that also applies to MCP-discovered tools, the orchestrator would be unable to invoke these tools directly. However, the current architecture calls these tools via dedicated client classes (`ContractEngineClient`, `CodebaseIntelligenceClient`) using direct MCP sessions, not through the orchestrator's SDK session. So this is likely benign.
- **Suggested Investigation:** Verify whether the Claude Agent SDK filters MCP tool calls through `allowed_tools`. If it does, add:
  ```python
  if "contract_engine" in servers:
      tools.extend([
          "mcp__contract_engine__get_contract",
          "mcp__contract_engine__validate_endpoint",
          "mcp__contract_engine__generate_tests",
          "mcp__contract_engine__check_breaking_changes",
          "mcp__contract_engine__mark_implemented",
          "mcp__contract_engine__get_unimplemented_contracts",
      ])
  if "codebase_intelligence" in servers:
      tools.extend([
          "mcp__codebase_intelligence__find_definition",
          "mcp__codebase_intelligence__find_callers",
          "mcp__codebase_intelligence__find_dependencies",
          "mcp__codebase_intelligence__search_semantic",
          "mcp__codebase_intelligence__get_service_interface",
          "mcp__codebase_intelligence__check_dead_code",
          "mcp__codebase_intelligence__register_artifact",
      ])
  ```

---

## Tool Name Consistency Matrix

| Tool Name (claude_md_generator.py) | Client Method (contract_client.py / codebase_client.py) | MCP call_tool name | Consistent? |
|---|---|---|---|
| `get_contract` | `ContractEngineClient.get_contract()` | `"get_contract"` | YES |
| `validate_endpoint` | `ContractEngineClient.validate_endpoint()` | `"validate_endpoint"` | YES |
| `generate_tests` | `ContractEngineClient.generate_tests()` | `"generate_tests"` | YES |
| `check_breaking_changes` | `ContractEngineClient.check_breaking_changes()` | `"check_breaking_changes"` | YES |
| `mark_implemented` | `ContractEngineClient.mark_implemented()` | `"mark_implemented"` | YES |
| `get_unimplemented_contracts` | `ContractEngineClient.get_unimplemented_contracts()` | `"get_unimplemented_contracts"` | YES |
| `find_definition` | `CodebaseIntelligenceClient.find_definition()` | `"find_definition"` | YES |
| `find_callers` | `CodebaseIntelligenceClient.find_callers()` | `"find_callers"` | YES |
| `find_dependencies` | `CodebaseIntelligenceClient.find_dependencies()` | `"find_dependencies"` | YES |
| `search_semantic` | `CodebaseIntelligenceClient.search_semantic()` | `"search_semantic"` | YES |
| `get_service_interface` | `CodebaseIntelligenceClient.get_service_interface()` | `"get_service_interface"` | YES |
| `check_dead_code` | `CodebaseIntelligenceClient.check_dead_code()` | `"check_dead_code"` | YES |
| `register_artifact` | `CodebaseIntelligenceClient.register_artifact()` | `"register_artifact"` | YES |

All 13 tool names are consistent across documentation, client implementations, and MCP call_tool invocations.

---

## Architecture Diagram (Data Flow)

```
YAML Config
    |
    v
load_config() -> AgentTeamConfig
    |
    v
apply_depth_quality_gating(depth, config)
    |  Sets: contract_engine.enabled, codebase_intelligence.enabled,
    |        agent_teams.enabled based on depth
    v
get_contract_aware_servers(config)
    |  Returns: { "firecrawl"?, "context7"?, "sequential_thinking"?,
    |              "contract_engine"?, "codebase_intelligence"? }
    |
    +---> _build_options(config) -> ClaudeAgentOptions
    |       |  mcp_servers -> options.mcp_servers
    |       |  recompute_allowed_tools(_BASE_TOOLS, mcp_servers)
    |       v
    |     ClaudeSDKClient (orchestrator session)
    |
    +---> create_contract_engine_session(config.contract_engine)
    |       |  -> ClientSession
    |       |  -> ContractEngineClient(session)
    |       |  -> ServiceContractRegistry.load_from_mcp(client)
    |       v
    |     Contract context for prompts
    |
    +---> create_codebase_intelligence_session(config.codebase_intelligence)
    |       |  -> ClientSession
    |       |  -> CodebaseIntelligenceClient(session)
    |       |  -> generate_codebase_map_from_mcp(client)
    |       v
    |     Codebase map context for prompts
    |
    +---> create_execution_backend(config)
    |       |  -> AgentTeamsBackend or CLIBackend
    |       v
    |     Task execution engine
    |
    +---> generate_hooks_config(config, project_dir)
    |       |  -> HookConfig
    |       |  -> write_hooks_to_project(hook_config, project_dir)
    |       v
    |     .claude/settings.local.json + .claude/hooks/*.sh
    |
    +---> write_teammate_claude_md(role, config, mcp_servers*, project_dir)
            |  * BUG: mcp_servers undefined in main() scope
            |  -> generate_claude_md(role, config, mcp_servers, contracts)
            v
          .claude/CLAUDE.md (per-role)
```

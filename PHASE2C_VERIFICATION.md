# Phase 2C: Codebase Intelligence Integration -- Verification Report

**Date:** 2026-02-23
**Verifier:** Claude Opus 4.6
**Status:** ALL CHECKS PASS

---

## 2C.1: MCP Client Lifecycle (`mcp_clients.py`)

### 2C.1.1: `create_codebase_intelligence_session()` calls `session.initialize()` before yield

**PASS** -- `mcp_clients.py:174-178`

```python
await asyncio.wait_for(
    session.initialize(),
    timeout=startup_timeout,
)
yield session
```

`session.initialize()` is called with `asyncio.wait_for` timeout guard, and `yield session` occurs only after initialization completes. Same pattern as the contract engine session (lines 94-98).

### 2C.1.2: All 3 env vars handled: DATABASE_PATH, CHROMA_PATH, GRAPH_PATH

**PASS** -- `mcp_clients.py:141-151`

```python
db_path = config.database_path or os.getenv("DATABASE_PATH", "")
if db_path:
    env_vars["DATABASE_PATH"] = db_path

chroma_path = config.chroma_path or os.getenv("CHROMA_PATH", "")
if chroma_path:
    env_vars["CHROMA_PATH"] = chroma_path

graph_path = config.graph_path or os.getenv("GRAPH_PATH", "")
if graph_path:
    env_vars["GRAPH_PATH"] = graph_path
```

Each of the 3 env vars:
- Reads from `config.<field>` first, falls back to `os.getenv()` with empty string default.
- Only includes in `env_vars` dict if non-empty (truthy check).
- Only non-empty vars are passed to the subprocess.

### 2C.1.3: SEC-001: Only specific env vars + PATH passed

**PASS** -- `mcp_clients.py:153-159`

```python
if env_vars:
    # SEC-001: Only pass specific env vars -- never spread os.environ
    # (would leak API keys and other secrets to MCP subprocesses).
    env = {
        "PATH": os.environ.get("PATH", ""),
        **env_vars,
    }
```

The env dict is constructed from scratch with only `PATH` plus the explicitly-constructed `env_vars` dict. `os.environ` is never spread. Comment explicitly references SEC-001. If no env vars are set, `env` remains `None` and is not passed at all.

### 2C.1.4: Exception wrapping to MCPConnectionError

**PASS** -- `mcp_clients.py:179-182`

```python
except (TimeoutError, ConnectionError, ProcessLookupError, OSError) as exc:
    raise MCPConnectionError(
        f"Failed to connect to Codebase Intelligence MCP server: {exc}"
    ) from exc
```

Catches 4 transient error types (`TimeoutError`, `ConnectionError`, `ProcessLookupError`, `OSError`) and wraps them in `MCPConnectionError` with `from exc` to preserve the chain. Identical pattern to contract engine session (lines 99-102).

---

## 2C.2: CodebaseIntelligenceClient Methods (`codebase_client.py`)

### 2C.2.1: All 7 methods exist

**PASS** -- All 7 methods present:

| # | Method | Line | Tool Name | SVC Tag |
|---|--------|------|-----------|---------|
| 1 | `find_definition` | 85 | `find_definition` | SVC-007 |
| 2 | `find_callers` | 121 | `find_callers` | SVC-008 |
| 3 | `find_dependencies` | 148 | `find_dependencies` | SVC-009 |
| 4 | `search_semantic` | 177 | `search_semantic` | SVC-010 |
| 5 | `get_service_interface` | 214 | `get_service_interface` | SVC-011 |
| 6 | `check_dead_code` | 239 | `check_dead_code` | SVC-012 |
| 7 | `register_artifact` | 267 | `register_artifact` | SVC-013 |

### 2C.2.2: Each method's failure default

**PASS** -- All methods return safe defaults on failure:

| Method | Default on Error | Evidence |
|--------|-----------------|----------|
| `find_definition` | `DefinitionResult()` (found=False) | line 117 |
| `find_callers` | `[]` | line 144 |
| `find_dependencies` | `DependencyResult()` (all empty lists) | line 173 |
| `search_semantic` | `[]` | line 210 |
| `get_service_interface` | `{}` | line 235 |
| `check_dead_code` | `[]` | line 263 |
| `register_artifact` | `ArtifactResult()` (indexed=False) | lines 301, 308 |

All methods also handle type-mismatch responses (e.g., `find_callers` checks `isinstance(data, list)` before returning, returning `[]` if the response is not a list).

### 2C.2.3: `register_artifact` does NOT use `_call_with_retry` (INT-005)

**PASS** -- `codebase_client.py:281-308`

```python
async def register_artifact(
    self,
    file_path: str,
    service_name: str = "",
    timeout_ms: float = 60000,
) -> ArtifactResult:
    """...Single attempt with timeout -- no retry (per INT-005)..."""
    try:
        result = await asyncio.wait_for(
            self._session.call_tool(
                "register_artifact",
                {"file_path": file_path, "service_name": service_name},
            ),
            timeout=timeout_ms / 1000,
        )
```

- Uses `asyncio.wait_for` directly on `self._session.call_tool()`.
- Does NOT call `_call_with_retry`.
- Docstring explicitly states: "Single attempt with timeout -- no retry (per INT-005)."
- Catches `asyncio.TimeoutError`, `OSError`, `ConnectionError` plus general `Exception` separately.

### 2C.2.4: All other 6 methods DO use `_call_with_retry`

**PASS** -- Each of the 6 non-register methods calls `_call_with_retry`:

| Method | Call Site |
|--------|----------|
| `find_definition` | `codebase_client.py:98` |
| `find_callers` | `codebase_client.py:132` |
| `find_dependencies` | `codebase_client.py:156` |
| `search_semantic` | `codebase_client.py:198` |
| `get_service_interface` | `codebase_client.py:221` |
| `check_dead_code` | `codebase_client.py:249` |

All use the import `from .contract_client import _call_with_retry, _extract_json` at the top of the module (line 23).

### 2C.2.5: Dataclasses: DefinitionResult, DependencyResult, ArtifactResult

**PASS** -- All 3 dataclasses defined with correct fields and defaults:

**DefinitionResult** (lines 33-40):
- `file: str = ""`
- `line: int = 0`
- `kind: str = ""`
- `signature: str = ""`
- `found: bool = False`

**DependencyResult** (lines 44-50):
- `imports: list[str] = field(default_factory=list)`
- `imported_by: list[str] = field(default_factory=list)`
- `transitive_deps: list[str] = field(default_factory=list)`
- `circular_deps: list[list[str]] = field(default_factory=list)`

**ArtifactResult** (lines 54-59):
- `indexed: bool = False`
- `symbols_found: int = 0`
- `dependencies_found: int = 0`

All use `field(default_factory=...)` for mutable defaults (correct pattern to avoid the shared-mutable-default dataclass pitfall).

---

## 2C.3: Codebase Map Integration (`codebase_map.py`)

### 2C.3.1: `generate_codebase_map_from_mcp()` function exists

**PASS** -- `codebase_map.py:969-1037`

Function signature:
```python
async def generate_codebase_map_from_mcp(
    client: "Any",
) -> str:
```

Takes a `CodebaseIntelligenceClient` instance, uses 3 MCP queries:
1. `client.search_semantic("main entry point module", n_results=20)` -- discover modules
2. `client.get_service_interface("")` -- broad service view
3. `client.check_dead_code("")` -- dead code detection

Returns a markdown string with sections: header, service info (endpoints/events), discovered modules (capped at 20), dead code candidates (capped at 10). Returns empty string on failure.

### 2C.3.2: Static map fallback when MCP is unavailable

**PASS** -- The static fallback is the primary `generate_codebase_map()` async function at `codebase_map.py:822-872`. This is the filesystem-based analysis path that performs full synchronous scanning via `_generate_map_sync()`. The MCP-backed `generate_codebase_map_from_mcp()` is the *alternative* path -- callers choose which to use based on whether MCP is available. Both coexist in the same module.

The MCP function itself has a fallback to empty string on failure (lines 1032-1037):
```python
except Exception as exc:
    logging.getLogger(__name__).warning(
        "generate_codebase_map_from_mcp failed: %s", exc, exc_info=True,
    )
    return ""
```

### 2C.3.3: Framework detection (JS and Python frameworks)

**PASS** -- `codebase_map.py:535-649`

**JS frameworks** (`_JS_FRAMEWORK_MAP`, lines 137-154): 14 entries covering next.js, express, react, vue, nuxt, svelte, angular, fastify, koa, nestjs, gatsby, remix, hono, electron. Detected from `package.json` via `dependencies`, `devDependencies`, and `peerDependencies` keys.

**Python frameworks** (`_PY_FRAMEWORK_NAMES`, lines 156-167): 10 entries covering fastapi, django, flask, starlette, tornado, sanic, aiohttp, bottle, falcon, litestar. Detected from:
- `pyproject.toml` via `[project].dependencies` and `[tool.poetry].dependencies` (with regex fallback for Python <3.11 without `tomllib`)
- `requirements.txt` via line-by-line regex parsing

Deduplication logic prevents the same framework appearing from multiple manifest files (line 584).

### 2C.3.4: CodebaseMap dataclass fields

**PASS** -- `codebase_map.py:85-96`

```python
@dataclass
class CodebaseMap:
    root: str                          # project root path
    modules: list[ModuleInfo]          # all discovered source modules
    import_graph: list[ImportEdge]     # directed import edges
    shared_files: list[SharedFile]     # high fan-in files (>=3 importers)
    frameworks: list[FrameworkInfo]    # detected frameworks
    total_files: int                   # len(modules)
    total_lines: int                   # sum of all module line counts
    primary_language: str              # most common language
```

Supporting dataclasses:
- `ModuleInfo` (lines 45-53): path, language, role, exports, imports, lines
- `ImportEdge` (lines 57-62): source, target, symbols
- `SharedFile` (lines 66-72): path, importers, fan_in, risk
- `FrameworkInfo` (lines 76-81): name, version, detected_from

---

## 2C.4: Architect MCP Client (`mcp_clients.py` ArchitectClient class)

### 2C.4.1: All 4 methods exist

**PASS** -- `mcp_clients.py:189-277`

| # | Method | Line | MCP Tool Name | Return Type |
|---|--------|------|---------------|-------------|
| 1 | `decompose` | 205 | `decompose` | `dict[str, Any]` |
| 2 | `get_service_map` | 223 | `get_service_map` | `dict[str, Any]` |
| 3 | `get_contracts_for_service` | 240 | `get_contracts_for_service` | `list[dict[str, Any]]` |
| 4 | `get_domain_model` | 259 | `get_domain_model` | `dict[str, Any]` |

### 2C.4.2: All use `_call_with_retry` from contract_client

**PASS** -- Each method imports and calls `_call_with_retry`:

| Method | Import + Call Location |
|--------|----------------------|
| `decompose` | lines 212-217 |
| `get_service_map` | lines 229-234 |
| `get_contracts_for_service` | lines 246-252 |
| `get_domain_model` | lines 268-274 |

All use `from .contract_client import _call_with_retry` (imported inside each method body, which is the deferred-import pattern consistent with the lazy MCP SDK import design).

### 2C.4.3: Safe defaults on failure

**PASS** -- All methods catch `Exception` and return safe defaults:

| Method | Default on Failure | Evidence |
|--------|-------------------|----------|
| `decompose` | `{}` | line 221 |
| `get_service_map` | `{}` | line 238 |
| `get_contracts_for_service` | `[]` | line 257 |
| `get_domain_model` | `{}` | line 277 |

Additionally, all methods validate return types before returning:
- Dict methods check `isinstance(data, dict)`, return `{}` if not
- List method checks `isinstance(data, list)`, returns `[]` if not

All failures are logged with `logger.warning(...)` including `exc_info=True` for stack traces.

---

## 2C.5: Existing Test Coverage (`test_codebase_client.py`)

### What IS tested

The test file is comprehensive with 9 test classes and approximately 55+ test methods:

| Test Class | Test ID | What It Covers | Tests |
|------------|---------|---------------|-------|
| `TestClientValidResponses` | TEST-031 | All 7 methods with valid MCP responses | 12 tests |
| `TestClientExceptionDefaults` | TEST-032 | All 7 methods with OSError exceptions + warning logged | 7 tests |
| `TestClientIsErrorDefaults` | TEST-033 | All 7 methods with `isError=True` MCP results | 7 tests |
| `TestGenerateCodebaseMapFromMCP` | TEST-034 | MCP-backed codebase map markdown output | 5 tests |
| `TestRegisterNewArtifact` | TEST-035 | `register_new_artifact()` delegation | 3 tests |
| `TestCodebaseIntelligenceConfigDefaults` | TEST-036 | Config defaults, custom values, `_dict_to_config` | 8 tests |
| `TestCodebaseIntelligenceMCPServer` | TEST-037 | `_codebase_intelligence_mcp_server()` env var handling | 8 tests |
| `TestCreateCodebaseIntelligenceSession` | TEST-038 | Session creation, ImportError, MCPConnectionError | 5 tests |
| `TestGetContractAwareServersCodebaseIntelligence` | TEST-039 | Server inclusion/exclusion based on enabled flags | 7 tests |
| `TestDefinitionResultDataclass` | -- | Dataclass defaults and construction | 2 tests |
| `TestDependencyResultDataclass` | -- | Dataclass defaults and construction | 2 tests |
| `TestArtifactResultDataclass` | -- | Dataclass defaults and construction | 2 tests |
| `TestClientReturnNoneFromMCP` | -- | Null/empty/wrong-type JSON responses | 6 tests |

### Specific coverage highlights

1. **Happy path**: All 7 client methods tested with valid JSON responses.
2. **Error path**: All 7 methods tested with `OSError` exception + `caplog` assertion for warning log.
3. **MCP isError**: All 7 methods tested with `isError=True` flag -- verifies safe defaults.
4. **Type safety**: Tests for wrong-type responses (dict when list expected, list when dict expected, null JSON).
5. **Config validation**: Tests for invalid `startup_timeout_ms` and `tool_timeout_ms` values.
6. **Server composition**: Tests for all 4 combinations of contract_engine + codebase_intelligence enabled/disabled.
7. **MCP server env vars**: Individual and combined env var tests, plus `os.environ` fallback test.
8. **Markdown output**: Tests for full sections, empty data, failure, module cap (20), dead code cap (10).

### Gaps in coverage (for Phase 3)

| Gap ID | Missing Coverage | Priority | Notes |
|--------|-----------------|----------|-------|
| GAP-01 | **`register_artifact` timeout behavior** -- No test verifies that `asyncio.wait_for` actually raises `TimeoutError` when the call exceeds `timeout_ms`. Current tests only test `OSError`. | HIGH | INT-005 compliance. Should mock `call_tool` with `asyncio.sleep(>timeout)` to verify timeout fires. |
| GAP-02 | **`_call_with_retry` retry behavior through codebase client** -- Tests inject `OSError` directly on `call_tool` but don't verify the 3-retry + backoff loop fires. The `_call_with_retry` logic is in `contract_client.py` but no test in `test_codebase_client.py` verifies retry count or backoff timing for the codebase client specifically. | MEDIUM | May be covered by `test_contract_client.py` for the shared function. |
| GAP-03 | **`create_codebase_intelligence_session` actual connection flow** -- Only `ImportError` and config storage are tested. No test verifies the full `stdio_client` -> `ClientSession` -> `initialize()` flow with mocked MCP SDK. | MEDIUM | Requires mocking `mcp.ClientSession`, `mcp.StdioServerParameters`, and `mcp.client.stdio.stdio_client`. |
| GAP-04 | **`create_codebase_intelligence_session` exception wrapping** -- No test verifies that `TimeoutError`/`ConnectionError`/`ProcessLookupError`/`OSError` are wrapped to `MCPConnectionError`. | HIGH | SEC-001 and error contract. Should mock `stdio_client` to raise each of the 4 exception types. |
| GAP-05 | **ArchitectClient methods** -- `ArchitectClient` has zero test coverage in `test_codebase_client.py`. All 4 methods (`decompose`, `get_service_map`, `get_contracts_for_service`, `get_domain_model`) are untested. | HIGH | Should have happy-path, error-default, and isError tests (same pattern as CodebaseIntelligenceClient). |
| GAP-06 | **`register_artifact` with custom `timeout_ms`** -- Default is 60000ms. No test passes a custom value to verify it is respected. | LOW | |
| GAP-07 | **`check_dead_code` with `service_name=None`** -- Tests only pass a string. The `None` path (no `service_name` in params) is untested. | LOW | Line 247: `if service_name is not None:` branch. |
| GAP-08 | **`search_semantic` default `n_results`** -- Tests verify custom `n_results=5` but don't verify that `n_results=10` (default) is omitted from the arguments dict (line 195-196: `if n_results != 10:`). | LOW | |
| GAP-09 | **`_codebase_intelligence_mcp_server` vs `create_codebase_intelligence_session` env var consistency** -- The `_codebase_intelligence_mcp_server()` in `mcp_servers.py:263-295` does NOT include `PATH` in the env dict, while `create_codebase_intelligence_session()` in `mcp_clients.py:156` DOES include `PATH`. This is a potential inconsistency. | MEDIUM | The `_codebase_intelligence_mcp_server()` is for Claude SDK `mcp_servers` config (which may handle PATH differently), while `create_codebase_intelligence_session()` is for direct MCP SDK stdio transport. May be intentional, but should be verified. |
| GAP-10 | **Integration between codebase_map.py and codebase_client.py** -- `register_new_artifact()` is tested but `generate_codebase_map_from_mcp()` is tested with a raw `AsyncMock`, not with a real `CodebaseIntelligenceClient` wrapping a mock session. | LOW | The current tests are sufficient for unit coverage, but an integration test would catch interface drift. |

---

## Summary

| Section | Checks | Pass | Fail | Notes |
|---------|--------|------|------|-------|
| 2C.1 MCP Client Lifecycle | 4 | 4 | 0 | Clean implementation |
| 2C.2 CodebaseIntelligenceClient | 5 | 5 | 0 | INT-005 properly implemented |
| 2C.3 Codebase Map Integration | 4 | 4 | 0 | Both static and MCP paths exist |
| 2C.4 Architect MCP Client | 3 | 3 | 0 | Consistent retry + safe-default pattern |
| 2C.5 Test Coverage | 2 | 2 | 0 | Comprehensive but 10 gaps identified |
| **TOTAL** | **18** | **18** | **0** | |

### Discrepancies Found

1. **ENV var PATH inconsistency** (GAP-09): `_codebase_intelligence_mcp_server()` in `mcp_servers.py` does NOT include `PATH` in its env dict, while `create_codebase_intelligence_session()` in `mcp_clients.py` does. This may be intentional (the Claude SDK may add PATH automatically for `mcp_servers` configs), but warrants a test or explicit documentation.

2. **No bugs found** in the implementation logic. All methods follow the established patterns consistently.

### Phase 3 Test Priority

For the upcoming test writing phase, the recommended priority order based on gaps:

1. **GAP-05** (HIGH): ArchitectClient -- 4 methods with zero coverage
2. **GAP-04** (HIGH): Session exception wrapping to MCPConnectionError
3. **GAP-01** (HIGH): `register_artifact` timeout enforcement
4. **GAP-09** (MEDIUM): ENV var PATH consistency verification
5. **GAP-03** (MEDIUM): Full session lifecycle mock test
6. **GAP-02** (MEDIUM): Retry behavior through codebase client
7. **GAP-07/08/06** (LOW): Edge case parameter variants
8. **GAP-10** (LOW): Integration test with real client wrapping mock session

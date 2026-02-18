# MCP Client Deep Dive Audit — Phase 1E

**Date:** 2026-02-17
**Auditor:** mcp-auditor
**Scope:** `contract_client.py`, `codebase_client.py`, `mcp_clients.py`
**Risk Area:** #1 — MCP SDK patterns inferred from web search (Context7 was unavailable)

---

## CHECK 1: `_extract_json()` Pattern (TECH-017)

**PRD Requirement (TECH-017):**
> `_extract_json(result: Any) -> Any` helper that iterates `result.content`, finds `TextContent` with `hasattr(content, "text")`, parses JSON, returns None on any failure.

### contract_client.py — `_extract_json()` (lines 62-80)

```python
def _extract_json(content: list[Any] | None) -> Any:
    if not content:
        return None
    try:
        text = content[0].text
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError, IndexError, TypeError):
        return None
```

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Iterates `result.content` | Yes — iterate over content items | **No** — directly accesses `content[0].text` (index-based, not iteration) | **PARTIAL** |
| Checks `hasattr(content, "text")` for TextContent | Yes — explicit type check | **No** — relies on `AttributeError` catch instead | **FAIL** |
| Parses `content.text` as JSON | `json.loads(text)` | `json.loads(text)` at line 78 | **PASS** |
| Returns None on failure | Yes | Yes — catches 4 exception types | **PASS** |
| Handles empty content list | Yes | Yes — `if not content: return None` at line 74 | **PASS** |
| Handles content being None | Yes | Yes — `if not content` covers `None` | **PASS** |

**Signature mismatch:** PRD says `_extract_json(result: Any)` taking the full result object, but implementation takes `content: list[Any] | None` (the `result.content` attribute). This is called from `_call_with_retry()` at line 137-139 which passes `getattr(result, "content", None)`. **Functionally equivalent but the indirection is split across two functions.** The caller in `_call_with_retry` does the `.content` extraction.

**Iteration vs index-access:** The PRD specifies "iterates result.content, finds TextContent." The implementation does `content[0].text` — takes only the first item. If the MCP server returns multiple content items with the text in a non-first position, this would miss it. However, for the Build 1 Contract Engine tools, all responses are single-item text content, so this works in practice.

**hasattr check:** The PRD explicitly says `hasattr(content, "text")` to identify TextContent. The implementation skips this and catches `AttributeError` instead. This is a defensive approach (exception-based type checking) rather than proactive type checking. In the MCP SDK, content items can be `TextContent` or `ImageContent` — the `ImageContent` has `data` and `mimeType` but no `text`. If an image content appears at index 0, the code would catch `AttributeError` and return None (losing any text content at later indexes). This is a minor risk since Build 1 tools only return text.

**Status: PARTIAL**
**Risk: MEDIUM** — Works for Build 1's known response format, but is not robust against mixed-content responses. The PRD-specified iteration+hasattr pattern is safer.

### codebase_client.py — `_extract_json()` / `_extract_text()`

The `codebase_client.py` does **not** define its own `_extract_json()` or `_extract_text()`. Instead, it imports `_call_with_retry` from `contract_client.py` at line 22:

```python
from .contract_client import _call_with_retry
```

This means it reuses the same extraction logic via the shared `_call_with_retry()` function, which calls `_extract_json()` / `_extract_text()` from `contract_client.py`.

**PRD (TECH-028):** "CodebaseIntelligenceClient._extract_json() must share the same implementation pattern" — satisfied by literally sharing the implementation.

**Status: PASS** (via delegation)

---

## CHECK 2: `_extract_text()` Pattern (TECH-018)

**PRD Requirement (TECH-018):**
> `_extract_text(result: Any) -> str` helper that iterates `result.content`, returns first text content, empty string if none.

### contract_client.py — `_extract_text()` (lines 83-97)

```python
def _extract_text(content: list[Any] | None) -> str:
    if not content:
        return ""
    try:
        return content[0].text or ""
    except (AttributeError, IndexError, TypeError):
        return ""
```

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Same iteration pattern as _extract_json | Iterate content items | Same index-access `content[0].text` | **PARTIAL** (same issue as CHECK 1) |
| Returns first text content | Yes | Yes — `content[0].text` | **PASS** |
| Returns empty string if none | Yes | Yes — returns `""` in all error paths | **PASS** |

**Same findings as CHECK 1** — uses index-access instead of iteration, does not use `hasattr` check.

**Status: PARTIAL**
**Risk: LOW** — The text extraction is only used for `generate_tests()` response (a string), where the MCP server always returns a single TextContent item.

---

## CHECK 3: Session Management

### 3A: `create_contract_engine_session()` (mcp_clients.py lines 42-96)

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Lazy import inside function body | `from mcp import ...` inside function | Lines 63-64: `from mcp import ClientSession, StdioServerParameters` + `from mcp.client.stdio import stdio_client` inside try block | **PASS** |
| ImportError message mentions "pip install mcp" | Yes | Line 67: `"MCP SDK not installed. pip install mcp"` | **PASS** |
| `stdio_client(server_params)` returns (read, write) tuple | Yes | Line 85: `async with stdio_client(server_params) as (read_stream, write_stream)` | **PASS** |
| `ClientSession(read, write)` creates session | Yes | Line 86: `async with ClientSession(read_stream, write_stream) as session` | **PASS** |
| `await session.initialize()` called immediately | Yes, mandatory | Line 88-91: `await asyncio.wait_for(session.initialize(), timeout=startup_timeout)` | **PASS** |
| `asyncio.wait_for()` for timeout | Yes | Line 88: wrapped in `asyncio.wait_for` | **PASS** |
| Each `call_tool()` wrapped in `asyncio.wait_for()` | Yes per PRD | **No** — `_call_with_retry()` calls `await session.call_tool()` at line 130 without `asyncio.wait_for()` | **FAIL** |
| On timeout: MCPConnectionError raised | Yes | Lines 93-96: catches tuple, raises MCPConnectionError | **PASS** |
| `StdioServerParameters(command, args, env, cwd)` — all 4 params | Yes, all 4 | Lines 76-80: only `command`, `args`, `env` — **missing `cwd`** | **FAIL** |
| env dict has ONLY database paths, NOT ANTHROPIC_API_KEY | Yes (SEC-001) | Line 74: `env = {**os.environ, "DATABASE_PATH": db_path}` — **SPREADS `os.environ` which INCLUDES `ANTHROPIC_API_KEY`** | **FAIL (CRITICAL)** |
| cwd set to config.server_root when non-empty | Yes (TECH-020) | **Not passed** to StdioServerParameters | **FAIL** |

**CRITICAL FINDING 1: Environment variable leakage (SEC-001 violation)**
Line 74: `env = {**os.environ, "DATABASE_PATH": db_path}`
This spreads the entire `os.environ` dict, which includes `ANTHROPIC_API_KEY` and any other secrets in the environment. The PRD (SEC-001) and TECH-020 explicitly say:
> "Must not pass ANTHROPIC_API_KEY or other secrets as MCP server environment variables — only pass database paths and configuration values."
> "env dict has DATABASE_PATH from config when non-empty, None otherwise"

The env dict should contain ONLY `{"DATABASE_PATH": db_path}`, NOT `{**os.environ, ...}`.

**CRITICAL FINDING 2: Missing `cwd` parameter**
TECH-020 says: "Must also pass `cwd=config.contract_engine.server_root` when non-empty to ensure MCP server runs from Build 1 project root."
The `StdioServerParameters` is constructed without `cwd`. The config has `server_root: str = ""` (TECH-015) which should be passed when non-empty.

**FINDING 3: Missing per-call timeout**
REQ-024 says: "Apply `tool_timeout_ms` as `asyncio.wait_for()` wrapper around each `session.call_tool()` invocation."
In `_call_with_retry()` (contract_client.py line 130), `session.call_tool()` is called directly without `asyncio.wait_for()`:
```python
result = await session.call_tool(tool_name, arguments)
```
Should be:
```python
result = await asyncio.wait_for(session.call_tool(tool_name, arguments), timeout=tool_timeout_ms/1000.0)
```
However, the `_call_with_retry` function has no access to `tool_timeout_ms` config since it only receives the session, not the config.

### 3B: `create_codebase_intelligence_session()` (mcp_clients.py lines 103-170)

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Lazy import inside function body | Yes | Lines 123-125: same lazy import pattern | **PASS** |
| ImportError message | Yes | Line 127: same message | **PASS** |
| `stdio_client()` returns (read, write) | Yes | Line 159: same pattern | **PASS** |
| `ClientSession(read, write)` | Yes | Line 160: same pattern | **PASS** |
| `await session.initialize()` immediately | Yes | Lines 162-165: same pattern with wait_for | **PASS** |
| StdioServerParameters with all 4 params | command, args, env, cwd | Lines 150-154: only command, args, env — **missing cwd** | **FAIL** |
| env has ONLY database paths | DATABASE_PATH, CHROMA_PATH, GRAPH_PATH | Line 148: `env = {**os.environ, **env_vars}` — **SPREADS os.environ** | **FAIL (CRITICAL)** |
| cwd set to config.server_root | Yes | **Not passed** | **FAIL** |
| Non-empty env vars only | Yes | Lines 136-147: correctly builds env_vars dict conditionally | **PASS** (the conditional building is correct, but the os.environ spread negates it) |

**Same CRITICAL findings as 3A apply here:**
1. SEC-001 violation: `os.environ` spread at line 148
2. Missing `cwd` parameter (TECH-020 equivalent for codebase intelligence)

**Status: FAIL**
**Risk: CRITICAL** — SEC-001 is a security requirement. The `os.environ` spread leaks `ANTHROPIC_API_KEY` and all other environment secrets to the MCP server subprocess.

---

## CHECK 4: Retry Logic

### Shared `_call_with_retry()` (contract_client.py lines 104-185)

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Retries on `(OSError, TimeoutError, ConnectionError)` | Exact tuple | Line 28: `_TRANSIENT_ERRORS = (OSError, TimeoutError, ConnectionError)` used at line 147 | **PASS** |
| Does NOT retry on `(TypeError, ValueError)` | Immediate fail | Lines 29, 143-145: `_NON_TRANSIENT_ERRORS = (TypeError, ValueError)` caught and re-raised immediately | **PASS** |
| Exponential backoff: 1s, 2s, 4s | Yes | Line 27: `_BACKOFF_SECONDS = [1, 2, 4]` used at line 150 | **PASS** |
| Max 3 retries | Yes | Line 26: `_MAX_RETRIES = 3`, loop at line 128: `for attempt in range(_MAX_RETRIES)` | **PASS** |
| After 3 failures: logs warning with `exc_info=True` | Yes | Lines 157-161: `logger.warning(..., exc_info=True)` | **PASS** |
| Returns safe default | Yes | After retry exhaustion, raises the exception — caught by per-method try/except | **PASS** (indirectly) |
| NEVER raises to caller | True for client methods | The retry function DOES raise. But each ContractEngineClient/CodebaseIntelligenceClient method wraps the call in try/except and returns safe defaults | **PASS** |

**Additional retry behavior note:** Lines 164-180 handle other exceptions (including `RuntimeError` from `isError` check) as pseudo-transient — they get retried too. This is slightly broader than the PRD's specification but is defensive.

### Per-method verification (ContractEngineClient — 6 methods)

| Method | Try/except? | Safe default on exception? | exc_info=True? | Status |
|--------|-------------|---------------------------|----------------|--------|
| `get_contract` (L211-236) | Yes (L234) | Returns `None` | Yes (L235) | **PASS** |
| `validate_endpoint` (L240-278) | Yes (L272) | Returns `ContractValidation(error=...)` | Yes (L276) | **PASS** |
| `generate_tests` (L282-307) | Yes (L305) | Returns `""` | Yes (L306) | **PASS** |
| `check_breaking_changes` (L311-335) | Yes (L333) | Returns `[]` | Yes (L334) | **PASS** |
| `mark_implemented` (L339-370) | Yes (L364) | Returns `{"marked": False}` | Yes (L368) | **PASS** |
| `get_unimplemented_contracts` (L374-398) | Yes (L393) | Returns `[]` | Yes (L396) | **PASS** |

### Per-method verification (CodebaseIntelligenceClient — 7 methods)

| Method | Try/except? | Safe default on exception? | exc_info=True? | Status |
|--------|-------------|---------------------------|----------------|--------|
| `find_definition` (L84-116) | Yes (L112) | Returns `DefinitionResult()` | Yes (L114) | **PASS** |
| `find_callers` (L120-143) | Yes (L139) | Returns `[]` | Yes (L141) | **PASS** |
| `find_dependencies` (L147-172) | Yes (L168) | Returns `DependencyResult()` | Yes (L170) | **PASS** |
| `search_semantic` (L176-209) | Yes (L205) | Returns `[]` | Yes (L207) | **PASS** |
| `get_service_interface` (L213-234) | Yes (L228) | Returns `{}` | Yes (L231) | **PASS** |
| `check_dead_code` (L238-259) | Yes (L253) | Returns `[]` | Yes (L255) | **PASS** |
| `register_artifact` (L263-293) | Yes (L287) | Returns `ArtifactResult()` | Yes (L289) | **PASS** |

**Status: PASS**
**Risk: LOW** — Retry logic is solid. All 13 client methods have proper try/except with safe defaults.

---

## CHECK 5: `call_tool()` Usage

### call_tool() format

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Format: `await session.call_tool("tool_name", {"param": value})` | Yes | Line 130: `result = await session.call_tool(tool_name, arguments)` where arguments is always a dict | **PASS** |
| `result.isError` handling | Check isError | Line 133: `if getattr(result, "isError", False)` — raises RuntimeError | **PASS** |

### Tool name and parameter verification against Build 1 PRD

| Client Method | Tool Name Called | Build 1 Tool Name | Match? | Parameters Match? |
|---------------|----------------|--------------------|--------|-------------------|
| `get_contract` | `"get_contract"` | REQ-060: `get_contract` | **PASS** | `{"contract_id": str}` matches |
| `validate_endpoint` | `"validate_endpoint"` | REQ-060: `validate_endpoint` | **PASS** | `{service_name, method, path, response_body, status_code}` matches |
| `generate_tests` | `"generate_tests"` | REQ-060: `generate_tests` | **PASS** | `{contract_id, framework, include_negative}` matches |
| `check_breaking_changes` | `"check_breaking_changes"` | REQ-060: `check_breaking_changes` | **PASS** | `{contract_id, new_spec}` matches |
| `mark_implemented` | `"mark_implemented"` | REQ-060: `mark_implemented` | **PASS** | `{contract_id, service_name, evidence_path}` matches |
| `get_unimplemented_contracts` | `"get_unimplemented_contracts"` | REQ-060: `get_unimplemented_contracts` | **PASS** | `{service_name}` matches |
| `find_definition` | `"find_definition"` | REQ-057: `find_definition` | **PASS** | `{symbol, language}` matches |
| `find_callers` | `"find_callers"` | REQ-057: `find_callers` | **PASS** | `{symbol, max_results}` matches |
| `find_dependencies` | `"find_dependencies"` | REQ-057: `find_dependencies` | **PASS** | `{file_path}` matches |
| `search_semantic` | `"search_semantic"` | REQ-057: `search_semantic` | **PASS** | `{query, language?, service_name?, n_results?}` matches |
| `get_service_interface` | `"get_service_interface"` | REQ-057: `get_service_interface` | **PASS** | `{service_name}` matches |
| `check_dead_code` | `"check_dead_code"` | REQ-057: `check_dead_code` | **PASS** | `{service_name}` matches |
| `register_artifact` | `"register_artifact"` | REQ-057: `register_artifact` | **PASS** | `{file_path, service_name}` matches |

### ArchitectClient tool names (mcp_clients.py)

| Client Method | Tool Name Called | Build 1 Tool Name (REQ-059) | Match? |
|---------------|----------------|-----------------------------|--------|
| `decompose` | `"decompose"` | REQ-059: `decompose` | **PASS** |
| `get_service_map` | `"get_service_map"` | REQ-059: `get_service_map` | **PASS** |
| `get_contracts_for_service` | `"get_contracts_for_service"` | REQ-059: `get_contracts_for_service` | **PASS** |
| `get_domain_model` | `"get_domain_model"` | REQ-059: `get_domain_model` | **PASS** |

**Parameter mismatch note for ArchitectClient.decompose():**
- Build 2 calls: `"decompose", {"description": description}` (line 198)
- Build 1 REQ-059 specifies: `decompose(prd_text: str)` — parameter name is `prd_text`, not `description`

This is a **FAIL** — the parameter name `"description"` does not match Build 1's `prd_text` parameter.

**Status: PARTIAL**
**Risk: MEDIUM** — All 13 Contract Engine + Codebase Intelligence tool calls match perfectly. The ArchitectClient `decompose()` has a parameter name mismatch (`description` vs `prd_text`).

---

## CHECK 6: ArchitectClient (INT-003)

**PRD Requirement (INT-003):**
> Create `ArchitectClient` class in `mcp_clients.py` following the same pattern as ContractEngineClient/CodebaseIntelligenceClient, wrapping all 4 tools with try/except returning empty defaults on failure.

### Location and existence

| Sub-check | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Exists in `mcp_clients.py` | Yes | Lines 177-264 | **PASS** |
| Wraps 4 tools | decompose, get_service_map, get_contracts_for_service, get_domain_model | All 4 present (lines 190, 210, 227, 246) | **PASS** |

### Error handling pattern

| Method | Try/except? | Returns empty default? | Status |
|--------|-------------|----------------------|--------|
| `decompose` (L190-208) | Yes (L206) | Returns `{}` | **PASS** |
| `get_service_map` (L210-225) | Yes (L223) | Returns `{}` | **PASS** |
| `get_contracts_for_service` (L227-244) | Yes (L242) | Returns `[]` | **PASS** |
| `get_domain_model` (L246-264) | Yes (L262) | Returns `{}` | **PASS** |

### Pattern comparison with ContractEngineClient/CodebaseIntelligenceClient

| Aspect | Contract/Codebase Clients | ArchitectClient | Status |
|--------|---------------------------|-----------------|--------|
| Uses `_call_with_retry()` | Yes | **No** — calls `session.call_tool()` directly | **FAIL** |
| Retry logic | 3 retries with backoff | **No retries** — single attempt | **FAIL** |
| `exc_info=True` in logging | Yes | **No** — only logs `%s` for exc | **PARTIAL** |
| `isError` check | Yes | Yes — `getattr(result, "isError", False)` | **PASS** |
| `_extract_json()` usage | Via `_call_with_retry` | Direct import: `from .contract_client import _extract_json` | **PASS** |

**FINDING: ArchitectClient lacks retry logic**
The PRD says "following the same pattern" — but ArchitectClient does NOT use `_call_with_retry()`. It calls `session.call_tool()` directly with no retry. If a transient network error occurs, the method fails immediately with a single attempt. This is inconsistent with the 3-retry pattern used by all 13 other client methods.

**FINDING: Parameter name mismatch for decompose**
As noted in CHECK 5, `decompose()` passes `{"description": description}` but Build 1's REQ-059 defines the parameter as `prd_text`. This will cause a runtime error when Build 1's MCP server receives an unexpected parameter name.

**Status: PARTIAL**
**Risk: MEDIUM** — Missing retry logic and parameter name mismatch. The ArchitectClient works for the happy path but is less resilient than the other two clients.

---

## Summary

| Check | Status | Risk | Key Issues |
|-------|--------|------|------------|
| **CHECK 1: _extract_json()** | PARTIAL | MEDIUM | Index-access instead of iteration; no hasattr check. Works for known Build 1 responses. |
| **CHECK 2: _extract_text()** | PARTIAL | LOW | Same as CHECK 1. Only used for single-item text responses. |
| **CHECK 3: Session Management** | **FAIL** | **CRITICAL** | (1) **SEC-001 violation**: `os.environ` spread leaks ANTHROPIC_API_KEY to MCP subprocess. (2) Missing `cwd` parameter. (3) Missing per-call `asyncio.wait_for()` timeout. |
| **CHECK 4: Retry Logic** | PASS | LOW | Solid implementation. All 13 methods have proper error handling. |
| **CHECK 5: call_tool() Usage** | PARTIAL | MEDIUM | 13/13 CE+CI tools match. ArchitectClient.decompose() has param name mismatch (`description` vs `prd_text`). |
| **CHECK 6: ArchitectClient** | PARTIAL | MEDIUM | Exists with all 4 tools. Missing retry logic and param name mismatch. |

## Critical Defects Requiring Fix

### DEFECT-001: SEC-001 Violation — Environment Variable Leakage (CRITICAL)
**Files:** `mcp_clients.py` lines 74, 148
**Impact:** `ANTHROPIC_API_KEY` and all environment secrets are passed to MCP server subprocesses
**Fix:** Replace `{**os.environ, "DATABASE_PATH": db_path}` with `{"DATABASE_PATH": db_path}` (and equivalent for codebase intelligence)
**Note:** However, the MCP subprocess needs `PATH` to find the Python executable. The fix should pass `PATH` only, not all of `os.environ`. Or better: pass `None` for env (which inherits parent env — this is the default for subprocess) and set only the needed vars via the server's config.

### DEFECT-002: Missing `cwd` Parameter in StdioServerParameters (HIGH)
**Files:** `mcp_clients.py` lines 76-80, 150-154
**Impact:** MCP servers may fail to find their modules if working directory differs from Build 1 project root
**Fix:** Add `cwd=config.server_root if config.server_root else None` to both `StdioServerParameters()` calls

### DEFECT-003: Missing Per-Call Timeout (MEDIUM)
**Files:** `contract_client.py` line 130
**Impact:** Individual MCP tool calls can hang indefinitely. The retry loop catches timeouts but they can only occur from the initial session.initialize() timeout.
**Fix:** Pass `tool_timeout_ms` through to `_call_with_retry()` and wrap `session.call_tool()` in `asyncio.wait_for()`

### DEFECT-004: ArchitectClient.decompose() Parameter Name Mismatch (MEDIUM)
**File:** `mcp_clients.py` line 198
**Impact:** Build 1's Architect MCP server expects `prd_text` parameter, but Build 2 sends `description`
**Fix:** Change `{"description": description}` to `{"prd_text": description}`

### DEFECT-005: ArchitectClient Missing Retry Logic (LOW-MEDIUM)
**File:** `mcp_clients.py` lines 190-264
**Impact:** ArchitectClient has no retry on transient errors, unlike the other two clients
**Fix:** Use `_call_with_retry()` from contract_client.py instead of direct `session.call_tool()` calls

## Informational Notes

### Note 1: _extract_json index-access vs iteration
The implementation uses `content[0].text` instead of iterating and checking `hasattr`. This is technically a deviation from TECH-017 but is functionally safe for Build 1's known responses (all single-item TextContent). Fixing this is LOW priority since Build 1 tools will not return multi-item or non-text content.

### Note 2: Session lifecycle
The session management correctly uses async context managers with `async with stdio_client()` and `async with ClientSession()`. The `session.initialize()` is correctly called with timeout before yielding. This is the correct MCP SDK pattern.

### Note 3: ArchitectClient session creation
There is no `create_architect_session()` function in `mcp_clients.py`. The ArchitectClient is presumably instantiated with a session obtained from a separate mechanism. This is not a defect — the PRD says it should be in `mcp_clients.py` following the same pattern, but a session creator for it was not explicitly required in Build 2 (it would be created in Build 3).

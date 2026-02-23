# Phase 2B: Contract Engine Integration -- Verification Report

**Date:** 2026-02-23
**Verifier:** Claude Opus 4.6
**Scope:** MCP Client Lifecycle, ContractEngineClient, ServiceContractRegistry, CONTRACT Scans, Existing Test Coverage

---

## 2B.1: MCP Client Lifecycle (`mcp_clients.py`)

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\mcp_clients.py`

### 2B.1.1: `create_contract_engine_session()` calls `session.initialize()` before yield

**PASS** -- Lines 94-98:
```python
await asyncio.wait_for(
    session.initialize(),
    timeout=startup_timeout,
)
yield session
```
`session.initialize()` is called (wrapped in `asyncio.wait_for`) and only after it completes does the generator yield the session to the caller.

### 2B.1.2: Timeout handling: `startup_timeout_ms / 1000.0`

**PASS** -- Line 88:
```python
startup_timeout = config.startup_timeout_ms / 1000.0  # convert to seconds
```
Correct conversion from milliseconds to seconds using floating-point division.

### 2B.1.3: Exception wrapping: TimeoutError/ConnectionError/ProcessLookupError/OSError -> MCPConnectionError

**PASS** -- Lines 99-102:
```python
except (TimeoutError, ConnectionError, ProcessLookupError, OSError) as exc:
    raise MCPConnectionError(
        f"Failed to connect to Contract Engine MCP server: {exc}"
    ) from exc
```
All four exception types are caught and re-raised as `MCPConnectionError` with `from exc` chaining.

### 2B.1.4: Lazy MCP SDK import with helpful ImportError message

**PASS** -- Lines 62-68:
```python
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    raise ImportError(
        "MCP SDK not installed. pip install mcp"
    )
```
The import is deferred to the function body (not at module level). On failure, a clear `ImportError` with install instructions is raised.

### 2B.1.5: SEC-001: Only specific env vars passed, never `os.environ` spread

**PASS** -- Lines 71-79:
```python
# SEC-001: Only pass specific env vars -- never spread os.environ
env: dict[str, str] | None = None
db_path = config.database_path or os.getenv("CONTRACT_ENGINE_DB", "")
if db_path:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DATABASE_PATH": db_path,
    }
```
Only `PATH` and `DATABASE_PATH` are passed. No `os.environ` spread anywhere. The comment explicitly documents SEC-001. The same pattern is applied in `create_codebase_intelligence_session()` (lines 138-159) with similar per-variable extraction.

---

## 2B.2: ContractEngineClient Methods (`contract_client.py`)

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contract_client.py`

### 2B.2.1: All 6 methods present

**PASS** -- All 6 methods are defined:

| # | Method | Lines | Tool Name |
|---|--------|-------|-----------|
| SVC-001 | `get_contract` | 216-241 | `get_contract` |
| SVC-002 | `validate_endpoint` | 245-283 | `validate_endpoint` |
| SVC-003 | `generate_tests` | 287-312 | `generate_tests` |
| SVC-004 | `check_breaking_changes` | 316-340 | `check_breaking_changes` |
| SVC-005 | `mark_implemented` | 344-375 | `mark_implemented` |
| SVC-006 | `get_unimplemented_contracts` | 379-406 | `get_unimplemented_contracts` |

### 2B.2.2: Failure defaults for each method

**PASS** -- Each method has a broad `except Exception` that returns the correct safe default:

| Method | Failure Default | Evidence |
|--------|----------------|----------|
| `get_contract` | `None` | Line 241: `return None` |
| `validate_endpoint` | `ContractValidation(error=str(exc))` | Line 283: `return ContractValidation(error=str(exc))` |
| `generate_tests` | `""` | Line 312: `return ""` |
| `check_breaking_changes` | `[]` | Line 340: `return []` |
| `mark_implemented` | `{"marked": False}` | Line 375: `return {"marked": False}` |
| `get_unimplemented_contracts` | `[]` | Line 406: `return []` |

### 2B.2.3: `_call_with_retry` implementation

**PASS** -- Lines 104-190:

- **3 retries**: `_MAX_RETRIES = 3` (line 26), loop `for attempt in range(_MAX_RETRIES)` (line 130).
- **Backoff [1,2,4]s**: `_BACKOFF_SECONDS = [1, 2, 4]` (line 27), used at line 155: `backoff = _BACKOFF_SECONDS[attempt]`.
- **Transient errors**: `_TRANSIENT_ERRORS = (OSError, TimeoutError, ConnectionError)` (line 28) -- retried with backoff.
- **Non-transient errors**: `_NON_TRANSIENT_ERRORS = (TypeError, ValueError)` (line 29) -- raised immediately at line 148-150 with no retry.
- **Other exceptions** (e.g., `RuntimeError` from `isError`): Also retried (lines 169-185), treated as transient.
- **MCP-level errors** (`result.isError`): Detected at line 138 and raised as `RuntimeError`, which then falls into the retry path.

### 2B.2.4: Response parsing (JSON content extraction)

**PASS** -- Two extraction helpers:

- `_extract_json` (lines 62-80): Reads `content[0].text`, parses via `json.loads()`. Returns `None` on any failure (`JSONDecodeError`, `AttributeError`, `IndexError`, `TypeError`).
- `_extract_text` (lines 83-97): Reads `content[0].text` directly. Returns `""` on any failure.
- `_call_with_retry` dispatches to the correct extractor via `extract_fn` parameter (lines 143-146).
- `generate_tests` uses `extract_fn="text"` (line 308); all others use the default `extract_fn="json"`.

---

## 2B.3: ServiceContractRegistry (`contracts.py`)

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contracts.py`

### 2B.3.1: `load_from_mcp` fetches contracts and falls back to `load_from_local` on failure

**PASS** -- Lines 706-741:
```python
async def load_from_mcp(self, client, *, cache_path=None):
    try:
        all_contracts = await client.get_unimplemented_contracts("")
        for contract_data in all_contracts:
            ...
            info = await client.get_contract(cid)
            ...
    except Exception as exc:
        _logger.warning("MCP load failed, falling back to local cache: %s", exc)
        if cache_path is not None:
            self.load_from_local(cache_path)
```
On any exception during MCP loading, falls back to `load_from_local(cache_path)` if a cache path was provided. Matches REQ-029.

### 2B.3.2: `save_local_cache` strips `securitySchemes` (SEC-003)

**PASS** -- Lines 838-876:
```python
spec = copy.deepcopy(contract.spec)
# SEC-003: Strip securitySchemes from OpenAPI specs
if isinstance(spec, dict):
    components = spec.get("components", {})
    if isinstance(components, dict) and "securitySchemes" in components:
        del components["securitySchemes"]
```
- Uses `copy.deepcopy` to avoid mutating the in-memory contract (line 848).
- Deletes `securitySchemes` from the `components` section (line 854).
- The rest of `components` (e.g., `schemas`) is preserved.

### 2B.3.3: `validate_endpoint` delegates to client

**PASS** -- Lines 776-796:
```python
async def validate_endpoint(self, client, service_name, method, path, response_body, status_code=200):
    return await client.validate_endpoint(
        service_name=service_name,
        method=method,
        path=path,
        response_body=response_body,
        status_code=status_code,
    )
```
Pure delegation. All parameters forwarded.

### 2B.3.4: `mark_implemented` delegates to client

**PASS** -- Lines 798-818:
```python
async def mark_implemented(self, client, contract_id, service_name, evidence_path=""):
    result = await client.mark_implemented(
        contract_id=contract_id,
        service_name=service_name,
        evidence_path=evidence_path,
    )
    if result.get("marked", False) and contract_id in self._contracts:
        self._contracts[contract_id].implemented = True
        self._contracts[contract_id].evidence_path = evidence_path
    return result
```
Delegates to client, then updates local state on success. Correctly checks both `result.get("marked", False)` and `contract_id in self._contracts` before mutating local state.

---

## 2B.4: CONTRACT Scans (`contract_scanner.py`)

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\contract_scanner.py`

### 2B.4.1: All 4 scans exist with correct severity levels

**PASS**

| Scan | Function | Check Prefix | Severity | Evidence |
|------|----------|-------------|----------|----------|
| CONTRACT-001 | `run_endpoint_schema_scan` | `CONTRACT-001:{contract_id}` | `error` | Line 356: `severity="error"` |
| CONTRACT-002 | `run_missing_endpoint_scan` | `CONTRACT-002:{contract_id}` | `error` | Line 522: `severity="error"` |
| CONTRACT-003 | `run_event_schema_scan` | `CONTRACT-003:{contract_id}` | `warning` | Line 674: `severity="warning"` |
| CONTRACT-004 | `run_shared_model_scan` | `CONTRACT-004:{contract_id}` | `warning` | Line 813: `severity="warning"` |

All severities match the specification: CONTRACT-001/002 are `error`, CONTRACT-003/004 are `warning`.

### 2B.4.2: Crash isolation in `run_contract_compliance_scan()`

**PASS** -- Lines 857-891: Each of the 4 scan calls is wrapped in its own `try/except`:
```python
# CONTRACT-001
try:
    v001 = run_endpoint_schema_scan(...)
    ...
except Exception as exc:
    logger.warning("CONTRACT-001 scan crashed: %s", exc, exc_info=True)

# CONTRACT-002
try:
    v002 = run_missing_endpoint_scan(...)
    ...
except Exception as exc:
    logger.warning("CONTRACT-002 scan crashed: %s", exc, exc_info=True)
```
Same pattern for CONTRACT-003 and CONTRACT-004. Each scan is independently crash-isolated.

### 2B.4.3: `_MAX_VIOLATIONS` cap at 100

**PASS** -- Line 29: `_MAX_VIOLATIONS = 100`

Enforcement is multi-layered:
- Each individual scan checks `len(violations) >= _MAX_VIOLATIONS` in inner loops (e.g., lines 300-301, 308-309, 357-358, 485-486, etc.).
- Each individual scan returns `violations[:_MAX_VIOLATIONS]` (lines 360, 526, 678, 815).
- The orchestrator also caps after combining: `violations = violations[:_MAX_VIOLATIONS]` (line 894).

### 2B.4.4: Route pattern detection covers Flask, FastAPI, Express, ASP.NET

**PASS** -- Lines 34-50:

| Framework | Pattern Variable | Lines |
|-----------|-----------------|-------|
| Flask | `_FLASK_ROUTE_PATTERNS` | 34-37 (2 patterns: `@*.route(...)` and `@*.get/post/...`) |
| FastAPI | `_FASTAPI_ROUTE_PATTERNS` | 39-41 (1 pattern: `@*.get/post/...`) |
| Express | `_EXPRESS_ROUTE_PATTERNS` | 43-45 (1 pattern: `(router|app).get/post/...`) |
| ASP.NET | `_ASPNET_ROUTE_PATTERNS` | 47-50 (2 patterns: `[HttpGet/Post/...]` and `[Route(...)]`) |

All four frameworks are covered. Used by `_extract_routes_from_file()` (lines 367-417) which dispatches based on file extension.

---

## 2B.5: Existing Test Coverage

### 2B.5.1: `test_contract_client.py`

**File:** `C:\MY_PROJECTS\agent-team-v15\tests\test_contract_client.py` (981 lines)

**What IS tested:**

| Test Class | Coverage Area | Tests |
|------------|--------------|-------|
| `TestClientValidResponses` (TEST-018) | All 6 methods with valid MCP responses | 7 tests |
| `TestClientExceptionDefaults` (TEST-019) | All 6 methods return safe defaults on OSError | 6 tests |
| `TestClientIsErrorDefaults` (TEST-020) | All 6 methods return safe defaults on `isError=True` | 6 tests |
| `TestExtractJson` (TEST-021) | `_extract_json` edge cases: valid JSON, invalid, empty, None, no text attr | 6 tests |
| `TestExtractText` (TEST-022) | `_extract_text` edge cases: valid, empty, None, null text | 5 tests |
| `TestSessionImportError` (TEST-023) | `create_contract_engine_session` ImportError when `mcp` missing | 1 test |
| `TestSessionDatabasePath` (TEST-024) | DATABASE_PATH config handling | 2 tests |
| `TestContractEngineConfigDefaults` (TEST-025) | All config defaults verified | 1 test |
| `TestContractEngineConfigParsing` (TEST-026) | YAML parsing, overrides tracking, backward compat | 7 tests |
| `TestContractEngineMCPServer` (TEST-027) | MCP server config dict generation | 5 tests |
| `TestServiceContractRegistryLoad` (TEST-028) | `load_from_mcp` (success + failure), `load_from_local` (success + missing) | 4 tests |
| `TestServiceContractRegistrySave` (TEST-029) | `save_local_cache` roundtrip | 1 test |
| `TestServiceContractRegistryOperations` (TEST-030) | `validate_endpoint`, `mark_implemented`, `get_unimplemented` | 4 tests |
| `TestSaveLocalCacheStripsSecurity` (TEST-030A) | SEC-003: strips securitySchemes, does not mutate in-memory | 2 tests |
| `TestRetryBackoff` (TEST-030B) | Retry on TimeoutError, exhausts retries then safe default | 2 tests |
| `TestNonTransientNoRetry` (TEST-030C) | TypeError/ValueError fail immediately (no retry) | 2 tests |
| `TestMCPConnectionError` (TEST-030D) | MCPConnectionError class basics | 3 tests |

**Total: ~57 tests**

### 2B.5.2: `test_contracts.py`

**File:** `C:\MY_PROJECTS\agent-team-v15\tests\test_contracts.py` (568 lines)

**What IS tested:**

| Test Class | Coverage Area | Tests |
|------------|--------------|-------|
| `TestContractSerialization` | JSON roundtrip, empty registry, version field, missing file, malformed JSON | 5 tests |
| `TestSymbolPresentPython` | Python symbol detection: function, async, class, const, annotated, `__all__`, private | 10 tests |
| `TestSymbolPresentTS` | TypeScript symbol detection: function, class, const, default, type, interface, enum, named export | 9 tests |
| `TestVerifyModuleContract` | Module contract verification with real files (Python/TS) | 5 tests |
| `TestVerifyWiringContract` | Wiring verification: happy path, missing export, missing files | 3 tests |
| `TestVerifyAllContracts` | Full registry verification: all pass, mixed, empty | 3 tests |
| `TestReadFileSafeErrors` | Binary file handled without crash | 1 test |
| `TestLanguageDetectionShared` | Language detection via shared `_lang` module | 13 tests |

**Total: ~49 tests**

### 2B.5.3: `test_contract_scanner.py`

**File:** `C:\MY_PROJECTS\agent-team-v15\tests\test_contract_scanner.py` (872 lines)

**What IS tested:**

| Test Class | Coverage Area | Tests |
|------------|--------------|-------|
| `TestEndpointSchemaScan` (TEST-050) | Missing field detection, no violations, empty contracts, skip non-openapi | 4 tests |
| `TestMissingEndpointScan` (TEST-051) | Missing Flask route, matching Flask/Express/ASP.NET routes | 4 tests |
| `TestEventSchemaScan` (TEST-052) | Missing event field, empty contracts, skip openapi | 3 tests |
| `TestSharedModelScan` (TEST-053) | Snake_case drift detection, no drift with correct casing | 2 tests |
| `TestContractComplianceScan` (TEST-054) | Combines results, caps at _MAX_VIOLATIONS, empty contracts, config disables | 4 tests |
| `TestCrashIsolation` (TEST-055) | One scan crash doesn't block others, all crash returns empty | 2 tests |
| `TestQualityStandards` (TEST-056/057) | Standards mapped to correct agent roles, content checks | 4 tests |
| `TestContractComplianceMatrix` (TEST-058/059/065) | Generate markdown, parse counts, update entry | 4 tests |
| `TestVerifyContractCompliance` (TEST-060) | Healthy/degraded/failed/unknown statuses, required keys | 6 tests |
| `TestContractScanConfig` (TEST-061) | All scans enabled by default | 1 test |
| `TestDepthGating` (TEST-062) | Quick/standard/thorough/exhaustive, user override | 5 tests |
| `TestFieldExtraction` (TEST-063) | TypeScript/Python/C# field extraction | 3 tests |
| `TestMilestoneHealthWithContracts` (TEST-066) | `check_milestone_health` uses min of ratios | 1 test |

**Total: ~43 tests**

---

## Summary of Findings

### All Verification Points: PASS

| Section | Verification Point | Status |
|---------|-------------------|--------|
| 2B.1.1 | `session.initialize()` before yield | PASS |
| 2B.1.2 | Timeout `startup_timeout_ms / 1000.0` | PASS |
| 2B.1.3 | Exception wrapping (4 error types -> MCPConnectionError) | PASS |
| 2B.1.4 | Lazy MCP SDK import with ImportError message | PASS |
| 2B.1.5 | SEC-001: Only specific env vars passed | PASS |
| 2B.2.1 | All 6 client methods present | PASS |
| 2B.2.2 | Each method's failure default correct | PASS |
| 2B.2.3 | `_call_with_retry`: 3 retries, backoff [1,2,4]s, transient classification | PASS |
| 2B.2.4 | Response parsing (JSON content extraction) | PASS |
| 2B.3.1 | `load_from_mcp` fallback to `load_from_local` | PASS |
| 2B.3.2 | `save_local_cache` strips securitySchemes (SEC-003) | PASS |
| 2B.3.3 | `validate_endpoint` delegates to client | PASS |
| 2B.3.4 | `mark_implemented` delegates to client | PASS |
| 2B.4.1 | All 4 scans with correct severity levels | PASS |
| 2B.4.2 | Crash isolation in orchestrator | PASS |
| 2B.4.3 | `_MAX_VIOLATIONS` cap at 100 | PASS |
| 2B.4.4 | Route detection: Flask, FastAPI, Express, ASP.NET | PASS |

### Discrepancies / Potential Issues Found

1. **Minor: `load_from_mcp` passes empty string `""` to `get_unimplemented_contracts`** (contracts.py:718). The `get_unimplemented_contracts` method on `ContractEngineClient` accepts `str | None` (contract_client.py:381) and only populates `service_name` in params when it is `not None`. Since `""` is falsy in Python but is not `None`, the check `if service_name is not None` (line 390) evaluates to `True`, so `service_name=""` IS passed to the MCP tool. This means the registry sends `{"service_name": ""}` to the server. Whether the MCP server treats `""` as "all services" or "service named empty string" depends on the server's implementation. This is not a bug per se, but a potential semantic mismatch. If the intent is to fetch ALL contracts, `None` would be safer.

2. **Minor: `_call_with_retry` categorizes `RuntimeError` as "other" but still retries** (contract_client.py:169-185). When `result.isError` is `True`, a `RuntimeError` is raised (line 140). This falls into the generic `except Exception` block (line 169) and gets retried. This means isError responses are retried 3 times, which might or might not be desirable -- if the server consistently returns an error for a tool call, retrying wastes time. However, this is a design choice rather than a bug.

3. **Minor: `generate_tests` uses `extract_fn="text"` but the MCP result content is still parsed via `_extract_text`** which returns `content[0].text`. If the MCP server returns generated test code as a JSON-wrapped string (e.g., `{"code": "...tests..."}`), only the raw text would be returned. This is likely correct behavior since the test code is expected to be plain text, but worth noting.

### Missing Test Coverage Areas for Phase 3

#### `mcp_clients.py` Gaps

1. **No integration test for `create_contract_engine_session` with a real or mocked stdio transport** -- the import error test (TEST-023) only tests the ImportError path. No test verifies the actual `stdio_client -> ClientSession -> initialize()` flow.
2. **No test for `MCPConnectionError` wrapping of each specific error type** (TimeoutError, ConnectionError, ProcessLookupError, OSError) during session creation -- only the class existence is tested (TEST-030D).
3. **No test for `create_codebase_intelligence_session`** -- it follows the same pattern but has no dedicated tests.
4. **No test for `ArchitectClient` methods** -- defined at lines 189-277, uses `_call_with_retry` but has zero test coverage.
5. **No test for SEC-001 env var isolation** -- verifying that `os.environ` is not spread in the actual `StdioServerParameters` call.
6. **No test verifying the `env=None` path** when `database_path` is empty (line 73-84, the `env` stays `None`).

#### `contract_client.py` Gaps

7. **No test for `ConnectionError` retry** -- only `TimeoutError` is tested in TEST-030B. `OSError` is tested in TEST-019 for safe defaults but not specifically for retry behavior.
8. **No test for `_extract_json` with nested content** (list of multiple content items) -- only the first item is ever read.
9. **No test for `_call_with_retry` timeout per-call** (`timeout_ms` parameter) -- the default 60000ms is never exercised.
10. **No test for partial MCP response** -- e.g., `get_contract` returning data with missing keys (all `.get()` calls should return defaults, but this path is untested).

#### `contracts.py` (ServiceContractRegistry) Gaps

11. **No test for `load_from_mcp` with `cache_path` fallback** -- TEST-028 tests MCP failure without a cache_path. The fallback path (`cache_path is not None -> load_from_local`) is untested.
12. **No test for `load_from_local` with invalid JSON** -- the `json.JSONDecodeError` handling (line 758) is untested.
13. **No test for `load_from_local` with `OSError`/`UnicodeDecodeError`** (line 752).
14. **No test for `mark_implemented` when MCP returns `{"marked": False}`** -- verifying local state is NOT updated.
15. **No test for `mark_implemented` when `contract_id` is not in `self._contracts`** -- verifying no KeyError.

#### `contract_scanner.py` Gaps

16. **No test for FastAPI-specific route detection** -- Flask and Express routes are tested (TEST-051), but FastAPI `@router.get(...)` is only implicitly covered since Flask and FastAPI share similar patterns.
17. **No test for `_normalize_path` function** -- path normalization (stripping trailing slashes, parameter substitution for `{id}`, `<type:name>`, `:name`) has no unit tests.
18. **No test for `_extract_routes_from_file` across all framework patterns** -- no direct unit test exists for this function.
19. **No test for `_has_svc_table` precondition check** (lines 74-100).
20. **No test for `_should_scan_file` with ScanScope filtering** -- only `scope=None` is exercised in tests.
21. **No test for `_collect_code_files` directory skip list** (`node_modules`, `.git`, etc.).
22. **No test for `_extract_asyncapi_events`** -- only indirectly tested through `run_event_schema_scan`.
23. **No test for `_extract_schema_fields` with `$ref` resolution** -- schema references are parsed but not directly tested.
24. **No test for `_to_snake_case` / `_to_camel_case` conversion functions**.
25. **No test for CONTRACT-004 PascalCase matching** (for C#) -- only snake_case drift is tested.
26. **No test verifying severity sort order** in `run_contract_compliance_scan` (line 896: errors before warnings).

#### Cross-Cutting Gaps

27. **No end-to-end test exercising the full pipeline**: config -> session -> client -> registry -> scanner.
28. **No test for `ArchitectClient`** (mcp_clients.py:189-277) -- 4 methods with zero coverage.
29. **No test for concurrent/parallel scan execution** -- all scans run sequentially, but no test verifies behavior under concurrent usage of `ServiceContractRegistry`.

---

## Recommendations for Phase 3

**High Priority (must-have):**
- Items 1, 2, 6, 11, 14, 15 -- These cover critical lifecycle and error-handling paths.
- Item 4/28 -- `ArchitectClient` has zero test coverage.

**Medium Priority (should-have):**
- Items 7, 10, 12, 13, 17, 18 -- Edge cases in retry logic, local cache handling, and route normalization.
- Item 26 -- Severity sort order verification.

**Low Priority (nice-to-have):**
- Items 8, 9, 16, 19, 20, 21, 22, 23, 24, 25 -- Internal helper functions and detailed edge cases.
- Items 27, 29 -- Integration and concurrency tests.

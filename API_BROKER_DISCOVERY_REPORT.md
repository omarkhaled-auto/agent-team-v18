# API Contract Broker — Discovery Report

## Executive Summary

The codebase has **substantial infrastructure** already in place for API contract management, but **zero tree-sitter involvement**: the entire API surface extraction is regex-based. A full pipeline exists — regex extractor (`api_contract_extractor.py`) → MCP contract engine (`contract_client.py` / `ServiceContractRegistry`) → compliance scanner (`contract_scanner.py`, CONTRACT-001..004) → post-build field scan (`quality_checks.py` API-001..004) → automated fix loop (recovery type `api_contract_fix`) — and the orchestrator enforces a strict **Wave A → B → C → D → E** sequence that already guarantees backend-before-frontend. Wave C generates an OpenAPI spec and a typed API client that Wave D consumes exclusively; Wave D is explicitly forbidden from touching backend source. The real gap is not absence of a broker — it's **extractor fidelity + handoff completeness**: the regex extractor cannot resolve nested DTOs across import graphs, decorator arguments are discarded, non-NestJS/Express/FastAPI frameworks (C#, Go, Pydantic-specific) are poorly covered, and if Wave C generation silently drops fields the frontend never learns. Backend and frontend **builder prompts themselves** barely mention API contracts — the detailed field-schema guidance lives in the orchestrator/architect/reviewer prompts, so violations are caught at review rather than prevented at write.

---

## Investigation Area 1: Tree-Sitter API Surface Extraction

### What Exists

#### 1. Tree-Sitter is NOT installed and NOT used

**The only references to "tree-sitter" in the entire codebase are regex patterns in the tech-stack detector** (`src/agent_team_v15/tech_research.py:123`, `251–252`) — used to *detect* the string "tree-sitter" in PRD text:

```python
# tech_research.py:123
(r"\btree[- ]?sitter\b\s*(?:v?(\d+(?:\.\d+)*))?", "tree-sitter", "other"),

# tech_research.py:251–252
"tree-sitter": ("tree-sitter", "other"),
"tree_sitter": ("tree-sitter", "other"),
```

`pyproject.toml:16–20` declares only:
```
dependencies = [
    "claude-agent-sdk>=0.1.26",
    "pyyaml>=6.0",
    "rich>=13.0",
]
```

No `tree_sitter` or `tree_sitter_languages` package is installed. No `.scm` query files exist anywhere in the repository.

#### 2. `get_service_interface()` is a remote RPC stub

**Location:** `src/agent_team_v15/codebase_client.py:214–235`

```python
async def get_service_interface(self, service_name: str) -> dict:
    """Retrieve the public interface of a service.

    Returns:
        Dict describing the service interface, or ``{}`` on error.
    """
    try:
        data = await _call_with_retry(
            self._session,
            "get_service_interface",
            {"service_name": service_name},
        )
        if isinstance(data, dict):
            return data
        return {}
```

This is a pass-through to an external Codex MCP service. There is **no local implementation**. The return shape is undocumented in this repo — extraction happens on the remote side.

#### 3. Local extraction is entirely regex-based in `api_contract_extractor.py`

The file has ~20 compiled regexes (lines 43–202) and the following extractor functions:

| Function | Line | What it extracts |
|---|---|---|
| `extract_nestjs_endpoints` | 385 | NestJS controllers: paths, HTTP methods, handler names, response types, `@Body()`/`@Query()` DTO refs |
| `extract_express_endpoints` | 511 | Express routes: paths + methods |
| `_extract_fastapi_endpoints` | 567 | FastAPI route decorators |
| `_extract_django_endpoints` | 624 | Django `urls.py` paths |
| `extract_dto_fields` | 663 | DTO class field names, types, decorator names |
| `extract_prisma_models` | 770 | Prisma models + field names/types/nullability |
| `extract_prisma_enums` | 817 | Prisma enum values |
| `extract_ts_enums` | 856 | TypeScript `enum` declarations |
| `extract_isin_enums` | 900 | `@IsIn([...])` functional enums |
| `extract_api_contracts` | 1013 | Orchestrator — produces `APIContractBundle` |

Key regex for DTO field extraction (lines 107–113):

```python
_DTO_FIELD_RE = re.compile(
    r"((?:@\w+\([^)]*\)\s*)+)"     # one or more decorators
    r"\s*(?:readonly\s+)?"
    r"(\w+)\s*[?!]?\s*:\s*"         # field name + colon
    r"([^;=\n]+)",                   # type (up to ; or newline)
    re.MULTILINE,
)
```

#### 4. Tree-sitter query files: none

There are **zero `.scm` files** in the repo. All "queries" are the inline regexes above. Any DTO/endpoint query would need to be written from scratch if tree-sitter were introduced.

### Capability Assessment

For the example `CreateOrderDto`:

| Capability | Supported? | Notes |
|---|---|---|
| Class name | ✅ | Via surrounding context in `_DTO_FIELD_RE` |
| Field names | ✅ | Group 2 of `_DTO_FIELD_RE` |
| Field types (as strings) | ✅ | Group 3, raw text |
| Optionality (`?`) | ⚠️ | Matched but not captured into a discrete field |
| Decorator names | ✅ | Via `_DECORATOR_NAME_RE` |
| Decorator arguments (`@MinLength(5)` → `5`) | ❌ | Not parsed |
| Nested DTO resolution (`CreateOrderItemDto[]` → its fields) | ❌ | Heuristic by filename convention only (`_enrich_endpoints_with_dtos`, line 1118); no import-graph traversal |
| Python Pydantic | ❌ | Not a targeted parser; Python DTOs treated only via generic field regex (dataclass-shaped) |
| C# record/class | ❌ | No C# parser |
| Go struct | ❌ | No Go parser |

**Bottom line:** Tree-sitter is a non-factor. The current extraction system is **regex-only**, **NestJS/Express/FastAPI-biased**, and **cannot follow type references across files**. Any "broker" design that depends on tree-sitter would start from zero integration. Any design that depends only on *what currently works* inherits these framework blind spots and the import-graph gap.

---

## Investigation Area 2: Contract Engine

### What Exists

#### 6. ContractEngineClient (`src/agent_team_v15/contract_client.py`)

Six MCP-backed methods, all wrapped in retry (3 attempts, exp. backoff, 60s timeout):

| Method | Line | What it validates | When | Failure mode |
|---|---|---|---|---|
| `get_contract(contract_id)` | 216–241 | Contract existence in MCP registry | Phase 0.5 discovery | Returns `None`, logs warning |
| `validate_endpoint(service, method, path, response_body, status)` | 245–283 | Response DTO fields vs. contract schema, HTTP status, method/path | Integration gate, post-milestone | Returns `ContractValidation(valid=False, violations=[...])`; never raises |
| `generate_tests(contract_id, framework, include_negative)` | 287–312 | Test-gen availability for contract | Optional, review phase | Returns `""` |
| `check_breaking_changes(contract_id, new_spec)` | 316–340 | Removed endpoints, changed types, removed required fields | Wave C / OpenAPI generation | Returns `[]` |
| `mark_implemented(contract_id, service, evidence_path)` | 344–375 | Tracks implementation evidence | Post-test-pass | Returns `{"marked": False}` |
| `get_unimplemented_contracts(service)` | 379–406 | Filters unfulfilled contracts | Phase 0.5, milestone prereq checks | Returns `[]` |

**Critical behavior:** validation failures return violations **but do not block the build** — logged as warnings/errors, decision deferred to later gates. MCP unavailability falls back to local cache (cli.py ~738); missing cache proceeds with empty registry (no validation).

#### 7. CONTRACT-001 through CONTRACT-004 (`src/agent_team_v15/contract_scanner.py`)

All four scans are orchestrated by `run_contract_compliance_scan` (lines 822–898), crash-isolated per scan, capped at 100 violations each.

**CONTRACT-001 — Endpoint Schema Verification** (`contract_scanner.py:261–360`)
- Compares backend response DTO field names to OpenAPI `spec` field names.
- Backend endpoint discovery by regex per language:
  - Flask: `@app.route()`, `@router.<verb>()` (lines 34–37)
  - FastAPI: `@router.<verb>()` (lines 39–40)
  - Express: `app.<verb>()`, `router.<verb>()` (lines 43–44)
  - ASP.NET: `[HttpGet]`/`[HttpPost]`/`[Route(...)]` (lines 47–49)
- DTO field extraction: TypeScript regex for `interface|class|type` bodies (lines 215–231), Python `^\s+(\w+)\s*:\s*\w` (234–244), C# `public\s+\w[\w<>\[\],\s]*?\s+(\w+)\s*\{` (247–258).
- Known FP sources: case-insensitive matches (342–344), regex misses nested objects, no inheritance chain traversal.

**CONTRACT-002 — Missing Endpoint** (`contract_scanner.py:430–526`)
- All OpenAPI `paths` must have matching code route.
- Path normalization: strip trailing `/`, lowercase, convert `{id}`/`<id>`/`:id` → `:param`.
- **Known FP:** fuzzy last-segment matching (line 111) can match unrelated endpoints sharing a suffix; parameter *names* not compared, only positions.

**CONTRACT-003 — Event Schema Verification** (`contract_scanner.py:563–678`)
- AsyncAPI: checks `emit`/`publish`/`dispatch`/`send`/`trigger` call sites (line 598–600) against channel payload schema.
- FP: regex matches unrelated functions named `publish`; missing events are only warnings (673).

**CONTRACT-004 — Shared Model Field Drift** (`contract_scanner.py:697–815`)
- Cross-language casing drift: `_to_snake_case` / `_to_camel_case` (685–694).
- Matching strategy (778–799): exact → snake → camel → PascalCase → case-insensitive.
- No abbreviation handling (`ID` vs `id`), no import-graph traversal.

#### 8. ServiceContractRegistry (`src/agent_team_v15/contracts.py:681–876`)

Data structure:
```python
class ServiceContractRegistry:
    _contracts: dict[str, ServiceContract]
```

Each `ServiceContract` (662–678): `contract_id`, `contract_type` (openapi/asyncapi/grpc), `provider_service`, `consumer_service`, `version`, `spec_hash`, `spec` (dict), `implemented`, `evidence_path`.

- Loaded from MCP (`load_from_mcp`, 706–740) with fallback to local JSON (`load_from_local`, 742–774) at `.agent-team/contract_cache.json`.
- Consumed by the CLI orchestrator before milestones, by agents via prompt injection, by the integration gate, and by the compliance scanner (converted to dict list, cli.py ~900).

#### 9. API_CONTRACTS.md / .json

- Generated by `api_contract_extractor.extract_api_contracts()`, called post-backend-milestone from cli.py ~1400.
- Stored at `.agent-team/API_CONTRACTS.json`.
- **Structure is programmatic JSON**, not markdown — `APIContractBundle` with `endpoints: list[EndpointContract]`, `shared_types`, `enums`, `timestamp`.
- `EndpointContract` fields: `method`, `path`, `controller`, `handler`, `request_type`, `response_type`, `request_fields: list[FieldInfo]`, `response_fields: list[FieldInfo]`, `description`.
- Companion **ENDPOINT_CONTRACTS.md** is the human-readable/agent-readable twin (explicitly called out in agents.py):
  > "API_CONTRACTS.json — machine-readable, auto-extracted from backend code (used by Python pipeline)"
  > "ENDPOINT_CONTRACTS.md — human-readable, generated for agent consumption (used by code-writers)"

#### 10. CONTRACTS.json (different artifact)

- Generated by the **architecture-lead agent** in Phase 0.2 (NOT auto-extracted).
- Describes **module boundaries, exports, imports, middleware order** — not API endpoints.
- Example schema:
  ```json
  {
    "version": "1.0",
    "modules": { "src/services/auth.py": { "exports": [{"name":"AuthService","kind":"class"}] } },
    "wirings": [{"source_module":"src/routes/auth.py","target_module":"src/services/auth.py","imports":["AuthService"]}],
    "middlewares": [{"entry_file":"src/server.ts","middleware_order":["errorHandler","cors","auth"]}]
  }
  ```
- Verified by `verify_all_contracts()` in `contracts.py:343–624` (module AST exports, wiring usage, middleware order).

### Capability Assessment

The Contract Engine already provides roughly **65–70%** of a contract broker's capabilities:

✅ Contract retrieval/caching (SVC-001, SVC-006)
✅ Endpoint validation with field-level checks (SVC-002)
✅ Cross-artifact compliance scanning (CONTRACT-001..004)
✅ Module/wiring contracts (CONTRACTS.json verification)
✅ Implementation-evidence tracking (SVC-005)

⚠️ Breaking-change detection is partial (no enum-value or field-reorder coverage); results aren't wired into blocking gates.
⚠️ Contract extraction is regex-based and NestJS-biased (see Area 1).
⚠️ Client generation is basic (httpx/fetch only).

❌ No live endpoint probing.
❌ No contract versioning/deprecation/migration.
❌ No consumer-registration tracking.
❌ No runtime enforcement middleware.
❌ No contract composition.

The engine validates contracts match code. It does not manage contract **lifecycle** or guarantee **extraction fidelity**. An API Contract Broker built on top would be mostly about (a) replacing the regex extractor with something import-aware, and (b) injecting the extracted surface into frontend context at the right pipeline point — both of which are narrow deltas against what's already here.

---

## Investigation Area 3: Builder Fleet Handoff

### What Exists

#### 11. Wave sequencing — backend strictly precedes frontend

`wave_executor.py:105–109`:

```python
WAVE_SEQUENCES = {
    "full_stack": ["A", "B", "C", "D", "E"],
    "backend_only": ["A", "B", "C", "E"],
    "frontend_only": ["D", "E"],
}
```

`wave_executor.py:792` — strict sequential loop:

```python
for wave_letter in waves[start_index:]:
    # Waves execute in strict order: A → B → C → D → E
```

- **Wave A** — Schema/entities/migrations only.
- **Wave B** — Backend services, controllers, DTOs, business logic.
- **Wave C** — Contracts: generates OpenAPI spec + typed API client from Wave B outputs.
- **Wave D** — Frontend, consuming **only** Wave C artifacts.
- **Wave E** — Verification.

`agents.py:7118` explicitly bars cross-wave inspection:

```python
"Do not inspect backend internals for endpoint contracts in this wave. Wave D consumes Wave C outputs only.",
```

**Parallelism** (`parallel_executor.py:28–41`): across milestones, milestone groups can execute in parallel. Within a milestone, waves are strictly sequential.

#### 12. Builder context per wave

**Wave B (backend)** — `agents.py:7044–7099`, `build_wave_b_prompt()`:
- Scaffolded files, IR endpoints, business rules, adapter ports, Wave A entities, predecessor artifacts.
- **Does NOT receive** frontend pages or UI acceptance criteria.

**Wave D (frontend)** — `agents.py:7111–7153`, `build_wave_d_prompt()`:
- **Wave C artifact only** (`client_exports`, `endpoints`, `openapi_spec_path`, `cumulative_spec_path`).
- Scaffolded page/component templates, acceptance criteria, i18n config.
- **Explicitly denied** access to backend source, service internals, and even PRD endpoint-path/DTO specifics (the prompt steers agents to the generated client).

Prompt excerpt (`agents.py:7120–7141`):
```python
"[GENERATED API CLIENT — THE ONLY ALLOWED BACKEND ACCESS PATH]",
_format_wave_c_contract_artifact(_artifact_dict(wave_c_artifact)),
"- Use the generated API client exports from Wave C. This is the only valid way to call the backend.",
"- `packages/api-client/*` is IMMUTABLE in this wave. Do not edit, refactor, rewrite..."
```

Working-directory files for any wave:
- `.agent-team/product-ir/product.ir.json`
- `.agent-team/artifacts/MILESTONE-wave-{A,B,C}.json` (saved via `_save_wave_artifact`, wave_executor.py:874–906)
- `.agent-team/STATE.json`
- `.agent-team/telemetry/*`

#### 13. CODEBASE_MAP — still used, structural not endpoint-level

`codebase_map.py:85–96`:
```python
@dataclass
class CodebaseMap:
    root: str
    modules: list[ModuleInfo]          # path, language, role, exports, imports
    import_graph: list[ImportEdge]
    shared_files: list[SharedFile]
    frameworks: list[FrameworkInfo]
    total_files: int
    total_lines: int
    primary_language: str
```

Role classification (223–225) identifies `controllers/`, `routes/`, `handlers/` directories as `"service"` but **does not extract endpoint paths, methods, or schemas**. It's a file-graph, not an API surface.

Referenced in the orchestrator system prompt (`agents.py:81–89`, Section 0: CODEBASE MAP).

#### 14. Post-Wave-B handoff — extraction happens, targeted at Wave C

`wave_executor.py:874–906` — artifact extraction:

```python
if wave_result.success and wave_letter != "C":
    artifact = None
    changed_for_extract = wave_result.files_created + [...]
    if extract_artifacts is not None:
        artifact = await _invoke(
            extract_artifacts, cwd=cwd, milestone_id=result.milestone_id,
            wave=wave_letter, changed_files=changed_for_extract, ...,
        )
    wave_result.artifact_path = _save_wave_artifact(artifact, cwd, result.milestone_id, wave_letter)
    wave_artifacts[wave_letter] = artifact
```

`_execute_wave_c()` (`wave_executor.py:644–679`) receives the full `wave_artifacts` dict including Wave B's extracted artifact — this is where `generate_contracts` (the OpenAPI spec + API client emitter) runs.

#### 15. Separate builders per wave

Each wave has its own specialized prompt and is driven by a separate invocation. No single builder handles both backend and frontend for the same milestone. Order is **fixed**, not uncontrolled.

### Capability Assessment

**Backend-to-frontend information flow EXISTS — but it is contract-first and narrow.** The Wave B → Wave C → Wave D pipeline is the very "broker" pattern the brief describes; it's already wired.

What currently propagates to the frontend (Wave D):

| Information | Available to Wave D? | Source |
|---|---|---|
| Endpoint methods + paths | ✅ | Wave C `endpoints_summary` |
| Request/response DTO types | ✅ | Generated API client types |
| Business logic | ❌ | Intentionally hidden |
| Entity relationships | ❌ | Only via DTO shape |
| Error-handling strategies | ⚠️ | Only if encoded in response types |
| Validation rules | ❌ | Not propagated |

**The real gaps are:**
1. The frontend gets only what the **generator produced**, not what the backend **actually built** — if Wave C's extractor misses a field (likely, given the regex limitations in Area 1), Wave D never learns.
2. No feedback loop: if Wave D discovers a missing/renamed field, that discovery does not re-trigger Wave B analysis or Wave C regeneration.
3. No cross-validation between Wave C's generated spec and Wave B's actual code.

---

## Investigation Area 4: Prompt Engineering

### What Exists

#### 16. Backend builder prompt (`agents.py:4282–4322`) — thin on API contracts

```
You are a BACKEND DEVELOPMENT SPECIALIST in an enterprise-scale Agent Team build.
Your expertise: NestJS, Prisma ORM, PostgreSQL, JWT authentication, REST APIs, TypeORM.

### Your Workflow
1. Read your domain assignment (files, requirements, contracts) from the task prompt
2. Read the shared scaffolding files (schema.prisma, app.module.ts) to understand the foundation
3. Read .agent-team/CONTRACTS.json for your API endpoints
4. Implement ALL your assigned requirements
5. Write COMPLETE, production-ready code — no stubs, no TODOs, no mock data

### Code Standards
- Every @Injectable must be in its module's providers array
- Every module using JwtAuthGuard must import AuthModule
- Use proper @Module imports — NestJS DI requires explicit wiring
- DTOs use class-validator decorators
- Services use PrismaService (already provided in shared scaffolding)
- Controllers handle errors with proper HTTP exceptions
```

No mention of field-naming conventions, enum serialization, or response-shape conventions in *this* prompt. These live in the orchestrator system prompt (`agents.py:1142–1238`, 1319–1346, 2750–2756), which backend builders inherit but may skim.

Orchestrator section the backend builder relies on (`agents.py:1142–1147`):

```
CRITICAL: Frontend and backend MUST agree on a field naming convention. Without this,
every field access results in `undefined` (camelCase vs snake_case mismatches).

### For NestJS/Prisma Projects (Foundation Milestone)
The FOUNDATION milestone MUST create a global response interceptor that transforms
ALL API responses from snake_case (Prisma convention) to camelCase (JavaScript convention):
```

Architect SVC-xxx mandate (`agents.py:2750–2756`):
```
RIGHT (exact field schema):
| SVC-001 | TenderService.getAll() | GET /api/tenders | GET | - | { id: number, title: string, status: "draft"|"active"|"closed", createdAt: string } |

Rules for field schemas:
1. Use the EXACT field names that the backend serializer will produce (e.g., camelCase for JSON)
2. For C# backends: properties are PascalCase in code but serialize to camelCase — write the camelCase version
```

#### 17. Frontend builder prompt (`agents.py:4324–4366`) — also thin

```
### Your Workflow
1. Read your domain assignment (files, requirements, contracts) from the task prompt
2. Read the shared scaffolding files (tailwind.config.ts, shared api.ts client) to understand the foundation
3. Read .agent-team/CONTRACTS.json for the API endpoints you consume
4. Implement ALL your assigned requirements
5. Write COMPLETE, production-ready code — no stubs, no TODOs, no placeholder UI
```

No mention of SVC-xxx or field schemas in the frontend builder prompt itself. The deep field guidance is in the **code-writer** prompt (`agents.py:2873–2891`):

```
## API CONTRACT COMPLIANCE (MANDATORY for SVC-xxx items)
When implementing ANY service method that corresponds to an SVC-xxx requirement:
1. OPEN REQUIREMENTS.md and find the SVC-xxx table row for this endpoint
2. READ the exact field names from the Response DTO column
3. Use EXACTLY those field names in your frontend model/interface — do NOT rename, re-case, or alias them
4. For C# backends: the JSON serializer produces camelCase (e.g., `TenderTitle` property → `tenderTitle` in JSON)
   - Your TypeScript/Angular interface MUST use the camelCase version: `tenderTitle: string`
   - NEVER use a different name like `title` or `tender_title`
5. For the Request DTO: use the exact field names from the Request DTO column in your HTTP request body
6. If REQUIREMENTS.md has no field schema (just a class name like "TenderDto"), flag it for the architect

VIOLATION: Using field names that don't match the SVC-xxx schema = API-001/API-002 contract violation.
```

#### 18. Code reviewer prompt (`agents.py:3167–3415`) — the strongest API contract layer

```
## API Contract Field Verification (MANDATORY for SVC-xxx items with field schemas)
For each SVC-xxx row that has an explicit field schema (not just a class name) in the Response DTO column:

1. **API-001: Backend field mismatch** — Open the backend DTO/model class. Verify that EVERY field name listed in the SVC-xxx Response DTO exists as a property. For C# classes, verify PascalCase property exists (it serializes to camelCase). Flag any missing or differently-named properties.

2. **API-002: Frontend field mismatch** — Open the frontend model/interface. Verify that EVERY field name listed in the SVC-xxx Response DTO is used with the EXACT same name. For TypeScript interfaces reading from C# backends, fields must be camelCase. Flag any field that is renamed, aliased, or uses a different casing convention.

3. **API-003: Type mismatch** — Verify that field types are compatible:
   - Backend `int`/`long` → Frontend `number`
   - Backend `string` → Frontend `string`
   - Backend `DateTime` → Frontend `string` (ISO 8601)
   - Backend `decimal`/`double` → Frontend `number`
   - Backend `bool` → Frontend `boolean`
   - Backend `enum` (numeric) → Frontend must have a mapping function, NOT raw numbers
   - Backend `List<T>` → Frontend `Array<T>` or `T[]`
```

Enum serialization check (`agents.py:3327–3334`):
```
### Enum Serialization (ENUM-004)
For .NET backends: VERIFY that Program.cs / Startup.cs configures JsonStringEnumConverter globally...
Without this, enums serialize as integers (0, 1, 2) but frontend code compares strings
("submitted", "approved"). This causes silent display failures and TypeError crashes.
```

#### 19. Architect prompt (`agents.py:2640–2825`) — generates field-level contracts

```
## Service-to-API Wiring Plan (MANDATORY for full-stack apps with frontend + backend)
1. List EVERY frontend service method that needs to call a backend API
2. Map each method to its corresponding backend controller action
3. Create SVC-xxx entries in REQUIREMENTS.md for EACH mapping
4. Create a **Service-to-API Wiring Map** table in the Integration Roadmap:
   | SVC-ID | Frontend Service.Method | Backend Endpoint | HTTP Method | Request DTO | Response DTO |
```

Plus the STATUS_REGISTRY block (`agents.py:2759–2789`):
```
## Status/Enum Registry (MANDATORY for projects with status or enum fields)
1. Entity Inventory: Every entity that has a status, state, type, or enum field
2. Complete Value List: Every possible value for each enum
3. State Transitions: Every valid state transition ...
4. Cross-Layer Representation: DB type, Backend API exact string, Frontend exact string — ALL THREE MUST MATCH.
5. Validation Rules: Backend MUST validate incoming status strings against the enum.

VIOLATION IDs:
- ENUM-001: Entity with status/enum field but no registry entry → HARD FAILURE
- ENUM-002: Frontend status string doesn't match backend enum value → HARD FAILURE
- ENUM-003: State transition not defined in registry → HARD FAILURE
```

ENDPOINT_CONTRACTS.md generator (`agents.py:4022–4041`):
```
## ENDPOINT_CONTRACTS.md Generation (MANDATORY for full-stack projects)
After generating CONTRACTS.json, you MUST also generate `.agent-team/ENDPOINT_CONTRACTS.md` containing:
1. For EVERY controller/route file, extract all HTTP endpoints
2. For each endpoint document:
   - HTTP method and path
   - Request body shape as a TypeScript interface
   - Response body shape as a TypeScript interface
   - Pagination wrapper format (if applicable)
3. Use ACTUAL field names from the backend code — do NOT invent or guess
4. The generated contract is FROZEN — frontend code MUST match it exactly
```

### Capability Assessment

**Strong at review, weak at authoring.** The architect/code-writer/reviewer chain produces and enforces field-level contracts well. But the backend and frontend *builder* prompts themselves barely mention API contracts — both say "read CONTRACTS.json" and stop there. Known failure modes:

1. Backend builder skips orchestrator guidance → implements DTOs with wrong casing → reviewer catches it late.
2. Frontend builder reads CONTRACTS.json without reading REQUIREMENTS.md SVC-xxx rows → silently uses wrong field names.
3. ENDPOINT_CONTRACTS.md is marked "FROZEN" (line 4034) but there's no mechanism for builders to flag inadequacies or propose changes.
4. Enum string-serialization guidance is .NET-only — Python/Node/Go projects have no analogous instruction.
5. Response-wrapper convention (`{data, meta}` for lists, bare object for single, etc., `agents.py:1248–1263`) lives only in the orchestrator system prompt — backend builders often miss it.
6. No contract versioning / change log → if ENDPOINT_CONTRACTS.md is updated mid-build, a frontend builder working against a cached read has no signal.
7. CONTRACT_GENERATOR_PROMPT tells the generator to "Use ACTUAL field names from the backend code — do NOT invent or guess", which means if backend DTOs are wrong, the generated contract codifies the wrong fields.

---

## Investigation Area 5: Quality Gate

### What Exists

#### 20. API-001..004 scans in `quality_checks.py`

Entry point: `run_api_contract_scan()` (`quality_checks.py:4876`), invoked from `cli.py:10380` during post-orchestration, looping up to `config.post_orchestration_scans.max_scan_fix_passes` until clean.

| Check | Fn | Line | Compares | Method |
|---|---|---|---|---|
| API-001 | `_check_backend_fields` | 4411 | Backend DTO properties ↔ SVC response_fields | Regex identifier extraction |
| API-002 (forward) | `_check_frontend_fields` | 4463 | Frontend type-defs ↔ SVC response_fields | 2-phase (models/interfaces/types/dto first; then services/clients/api) |
| API-002 (backward) | `_check_frontend_extra_fields` | 4750 | Frontend interface declarations ↔ SVC schema | TS interface body parsing with `_RE_TS_INTERFACE_FIELD` |
| API-003 | `_check_type_compatibility` | 4541 | Type hints vs `_TYPE_COMPAT_MAP` (4534) | Normalization + lookup |
| API-004 | `_check_request_field_passthrough` | 5793 | Frontend POST/PUT payloads ↔ backend accepted params | Regex HTTP-call extraction |
| ENUM-004 | `_check_enum_serialization` | 4578 | .NET Program.cs/Startup.cs for `JsonStringEnumConverter` | String search |

SVC rows parsed by `_parse_svc_table()` (4319) — supports both 5- and 6-column formats. Field schemas via `_parse_field_schema()` (4269), accepts JSON-like `{ id: number, title: string }` or bare `{ id, email }`.

#### 21. `_check_frontend_fields()` walkthrough (`quality_checks.py:4463`)

Phase 1 — type-definition priority (4479–4493):
```python
type_def_patterns = [r'(?:models?|interfaces?|types?|dto)']
type_def_files: list[Path] = []
for pat in type_def_patterns:
    type_def_files.extend(_find_files_by_pattern(project_root, pat))
```

Identifier extraction (`_extract_identifiers_from_file`, 4383):
```python
def _extract_identifiers_from_file(content: str) -> set[str]:
    return set(re.findall(r'\b[a-zA-Z_]\w*\b', content))
```

This is a **bag-of-identifiers** check — it only verifies the field name appears *somewhere* in a type-def file. It does not check the field is actually in the right interface, correct type, or associated with the right endpoint.

Violation emit (4520–4531):
```python
if field_name not in check_ids:
    violations.append(Violation(
        check="API-002",
        message=(
            f"{contract.svc_id}: Frontend missing field '{field_name}' "
            f"from response schema. Expected type: {type_hint}. "
            f"The frontend model/interface must use this exact field name."
        ),
        file_path="REQUIREMENTS.md", line=0, severity="error",
    ))
```

#### 22. Bidirectional checks confirmed

`quality_checks.py:4949–4956`:
```python
for contract in contracts_with_schemas:
    if len(violations) >= _MAX_VIOLATIONS:
        break
    _check_backend_fields(contract, project_root, violations)        # API-001
    _check_frontend_fields(contract, project_root, violations)       # API-002 forward
    _check_type_compatibility(contract, project_root, violations)    # API-003
    _check_frontend_extra_fields(contract, project_root, violations) # API-002 backward
```

Both directions covered: missing fields in the frontend (backend sends data frontend won't read) AND phantom fields in the frontend interface (frontend expects data backend won't send).

#### 23. Fix loop

`cli.py:10390–10420`:
```python
api_contract_violations = run_api_contract_scan(Path(cwd), scope=scan_scope)
if api_contract_violations:
    print_warning(f"API contract scan: {len(api_contract_violations)} field mismatch violation(s) found.")
    if _fix_pass == 0:
        recovery_types.append("api_contract_fix")
    if _max_passes > 0:
        api_fix_cost = asyncio.run(_run_api_contract_fix(
            cwd=cwd, config=config, api_violations=api_contract_violations, ...
        ))
```

Fix agent receives **field-name-specific** detail, not a generic message. From `_run_api_contract_fix` / `_build_api_contract_fix_prompt` (`cli.py:5479`, 5493–5510):

```python
violation_text = "\n".join(
    f"  - [{v.check}] {v.file_path}:{v.line} — {v.message}"
    for v in api_violations[:20]
)
fix_prompt = (
    f"[PHASE: API CONTRACT FIX]\n\n"
    f"API contract violations found:\n{violation_text}\n\n"
    f"INSTRUCTIONS:\n"
    f"1. For API-001 (backend field missing): add missing property to DTO, exact name\n"
    f"2. For API-002 (frontend field mismatch): add missing field to frontend model/interface\n"
    f"3. For API-003 (type mismatch): verify field types compatible\n"
)
```

Violation dedup: `get_violation_signature()` (677) + `track_fix_attempt()` (745) — violations exceeding `MAX_FIX_ATTEMPTS = 2` are excluded from subsequent passes.

Fix executor pipeline (`fix_executor.py:55`): `execute_unified_fix()` classifies the fix as `patch` vs `full`, escalates `contract_sensitive` changes (API DTO/controller files) to full build, and runs regression check (422).

### Capability Assessment

**Post-build field-level verification is comprehensive (~85% production-ready):**

✅ Bidirectional (forward + backward) field checks.
✅ Multi-language extraction (C#, TS/JS, Python).
✅ Field-specific violation messages, not generic.
✅ Automated fix loop with repeat-detection and regression testing.
✅ Configurable scan scope (change-aware via `ScanScope`).

⚠️ `_check_frontend_fields` is bag-of-identifiers — high FP risk if a field name appears coincidentally in a type file.
⚠️ Type checking is table-lookup, not full static analysis; generic types skipped.
⚠️ Enum serialization check is .NET-specific.
⚠️ Depends entirely on REQUIREMENTS.md SVC-xxx tables having proper field schemas; if the architect produced bare class names, field-level validation skips that row.

---

## Investigation Area 6: Failure Data

### What Exists

#### 24. Known API mismatch problems documented in prompts

`agents.py:1142–1143`:
> "CRITICAL: Frontend and backend MUST agree on a field naming convention. Without this, every field access results in `undefined` (camelCase vs snake_case mismatches)."

`agents.py:1181–1184` — query-param mismatch:
> "frontend filters silently fail (e.g., frontend sends `buildingId` but backend reads `building_id`)"

`agents.py:1193–1202` — request-body rejection:
> "frontend POSTs with `{ buildingId: \"...\" }` are silently rejected when the DTO expects `building_id` (especially with `forbidNonWhitelisted: true`)"

`agents.py:1230–1238` — prohibited defensive pattern:
> frontend code using `const name = item.buildingName || item.building_name || item.name` is called out as a broken-serialization tell.

`audit_prompts.py:527`:
> "Field name case mismatch (camelCase vs snake_case) — FAIL (HIGH)"

`audit_prompts.py:531–537`:
> "The backend ValidationPipe uses forbidNonWhitelisted: true — any property name that doesn't match a DTO field causes an immediate 400 Bad Request rejection"

`audit_prompts.py:569–573`:
> "Frontend expects field `name` but backend returns `fullName` — FAIL (HIGH)"
> "Nested object shape mismatch (e.g., `user.address.city` vs `user.addressCity`) — FAIL (HIGH)"

`audit_prompts.py:1164–1179` — common builder failure modes:
> "Pagination wrapper mismatch: Backend returns `{data: [], meta: {total, page}}` but frontend expects a flat array — causes 'Cannot read property map of undefined'"
> "Enum value mismatch: Backend sends numeric enum (0, 1, 2), frontend expects string enum ('ACTIVE', 'INACTIVE') — display shows '0' instead of 'Active'"
> "Form field name mismatch: Frontend sends `firstName` but backend DTO expects `first_name` — field silently ignored, saved as null"

#### 25. Recovery type for API contract mismatches

Recovery type: **`"api_contract_fix"`** (`cli.py:10397`).

Classification (`quality_checks.py:650`): `FIXABLE_CODE` — not infrastructure.

Fix-prompt generator: `_build_api_contract_fix_prompt` at `cli.py:5479`, with per-violation detail (see §23).

#### 26. Quality standards with API-consistency pattern IDs

`code_quality_standards.py`:

**FRONT-020 — DTO/Enum Mismatch** (95–98):
> "NEVER assume frontend enum values match backend enum values without verification... Backend may return numeric enums (0, 1, 2) while frontend uses string enums ('admin', 'manager'). FIX: Create mapping functions (mapApiRole, mapTenderStatus) in model files. Apply in services."

**FRONT-022 — Defensive Response Shape Handling** (105–109):
> "NEVER use defensive patterns like `Array.isArray(res) ? res : res.data || []`... If the frontend needs defensive handling, the backend response shape is wrong — fix the backend."

**FRONT-023 — Hardcoded Role/Enum Values** (111–115):
> "Role strings like `'technician'` in frontend MUST match the DB seed exactly (`'maintenance_tech'`). FIX: Create a shared constants file sourced from the Enum Registry."

**FRONT-024 — Auth Flow Assumption** (117–121):
> "NEVER implement an auth flow based on assumptions about the backend... If frontend expects challenge-token MFA but backend expects inline MFA code = locked-out users."

**BACK-028 — Route Structure Mismatch** (266–270):
> "NEVER call a nested route (`/buildings/:id/floors`) when the backend controller is top-level (`/floors`). This causes 404 errors... Frontend API paths MUST match the exact controller route prefix."

**Additional corroborating project docs:**

`ROOT_CAUSE_MAP.md:151–175` (Category 2 ENUM):
> "Enum Registry is an LLM-generated document, with no automated enforcement... the builder has no code in `quality_checks.py` or `integration_verifier.py` that actually parses the Prisma schema's pseudo-enums and cross-references them against frontend string constants... C-01 is a case where the DB seeds `maintenance_tech` but frontend queries for `role=technician`."

`ROOT_CAUSE_MAP.md:27` (Category 5 SERIALIZATION):
> "Disagreement on response structure between frontend and backend — camelCase/snake_case field naming, array-vs-{data,meta} wrapping, nested object shapes, pagination metadata location"

`ROOT_CAUSE_MAP.md:66` — H-11:
> "50+ field name fallbacks indicating interceptor inconsistency"

`CRITICAL_FIX_REPORT.md:60`:
> "Field-level contract compliance | FIELD-BLIND | URL-only matching | Response field name matching added"

---

## Gap Analysis Summary

| Capability | Status | What Exists | What's Missing |
|---|---|---|---|
| **Backend API extraction (tree-sitter)** | ❌ NONE | Zero tree-sitter integration. Only string-detection regex in `tech_research.py`. | Entire tree-sitter toolchain — grammars, parser setup, `.scm` queries. Not required if regex path is kept. |
| **Backend API extraction (regex)** | ✅ PARTIAL | Full NestJS extractor in `api_contract_extractor.py` (endpoints, DTOs, enums, Prisma). Good Express/FastAPI basics. | C# / Go / Pydantic-native extractors; decorator-argument parsing; cross-file type resolution via import graph. |
| **DTO/model field extraction** | ✅ PARTIAL | `extract_dto_fields`, `extract_prisma_models`, `extract_ts_enums`, `extract_isin_enums`. Captures names, types, decorator names. | Nested DTO expansion (`CreateOrderItemDto[]` is captured as a string only). Decorator arguments. Validation-constraint metadata. |
| **Backend-to-frontend handoff** | ✅ EXISTS | Wave A→B→C→D is strict; Wave C generates OpenAPI + typed API client; Wave D consumes only Wave C artifacts (`agents.py:7118–7141`). | Cross-check between Wave C generated spec and Wave B actual code. Feedback loop from Wave D back to Wave B/C if fields mismatch. Change-log/versioning on ENDPOINT_CONTRACTS.md. |
| **Frontend prompt guidance** | ⚠️ THIN IN BUILDER, RICH ELSEWHERE | `agents.py:2873–2891` code-writer prompt has strong SVC-xxx/API-001/002 guidance; reviewer prompt (3167–3415) enforces field-level checks. | Frontend **builder** prompt (4324–4366) doesn't explain SVC-xxx or link to REQUIREMENTS.md schema format. High risk of builder skipping the detailed contract. |
| **Post-build field verification** | ✅ COMPREHENSIVE | API-001..004 bidirectional scans (`quality_checks.py:4411–4956`); CONTRACT-001..004 compliance scans (`contract_scanner.py`). | Bag-of-identifiers FP in `_check_frontend_fields` (file-level, not interface-level). Type-check is lookup-table, not AST. Enum-serialization check is .NET-only. |
| **Fix loop for API mismatches** | ✅ COMPLETE | Recovery type `api_contract_fix` (`cli.py:10397`); field-specific fix prompt (`cli.py:5479`); repeat-detection; `FIXABLE_CODE` classification; regression check. | Fix loop depends on the extractor/scanner catching issues first — if extraction misses a field (see Areas 1, 2), fix loop never fires. |
| **Contract lifecycle management** | ❌ MISSING | ENDPOINT_CONTRACTS.md / API_CONTRACTS.json are regenerated per build; CONTRACTS.json is one-shot architecture artifact. | Versioning, deprecation, consumer-registration tracking, runtime enforcement middleware, contract composition, contract approval workflow. |

---

## Raw Findings

1. **`api_contract_extractor.py` is already the closest thing to a "broker extractor"** — it exists, runs after backend milestones, and produces a programmatic `APIContractBundle` (endpoints, shared types, enums). Its fidelity is the main variable: it handles NestJS/Prisma well, Express/FastAPI basically, and has no C#/Go/Pydantic-native parser.

2. **`ENDPOINT_CONTRACTS.md` already exists as the human-readable handoff artifact** (`agents.py:4022–4041`) but is generated by the contract-generator agent (LLM), not by the deterministic extractor. This is a fidelity risk: the LLM generator can miss, invent, or miscopy fields the regex extractor captured correctly, and vice versa.

3. **Wave C is the existing "broker injection point"** — it already sits between Wave B (backend write) and Wave D (frontend write). Any broker enhancement would slot here, not require new pipeline position.

4. **The frontend builder is already forbidden from reading backend source** (`agents.py:7118`). This means "inject backend API surface into frontend context" is already the intended architecture; the question is only what to inject and how faithfully.

5. **`_check_frontend_fields` is a bag-of-identifiers check**, not a structural interface check. A field name that merely appears in any file matching `models?|interfaces?|types?|dto` satisfies it — a real frontend-side mismatch (e.g., field is in wrong interface) can pass the scan. This is a latent FN in the existing verification.

6. **`ROOT_CAUSE_MAP.md:151–175` explicitly flags** that enum registries are "LLM-generated document, with no automated enforcement" and calls out `quality_checks.py` / `integration_verifier.py` as the place real enforcement *should* live but doesn't. This is a pre-existing acknowledged gap directly relevant to the broker.

7. **`CRITICAL_FIX_REPORT.md:60`** explicitly notes a prior fix moving the system from "FIELD-BLIND | URL-only matching" to "Response field name matching added" — so the field-level verification is a recent capability, consistent with its current half-finished state (bag-of-identifiers).

8. **CONTRACTS.json and API_CONTRACTS.json are different artifacts serving different purposes** and are easy to confuse when reading the codebase: CONTRACTS.json = module/wiring contracts (architect-authored); API_CONTRACTS.json = endpoint/DTO/enum extraction (post-backend). Any broker work must be clear about which it's touching.

9. **ENUM-001..004 and API-001..004 violation IDs are already established**, both in the prompts (reviewer, architect) and in the scanner code. New broker work should likely reuse these IDs rather than introduce new ones.

10. **No contract versioning exists anywhere.** ENDPOINT_CONTRACTS.md is regenerated fresh each build; there is no diff/hash/version pin that a frontend builder could use to detect that the contract it read earlier is now stale.

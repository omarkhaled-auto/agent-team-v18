# Phase C — Wave 1 Architecture Discovery Report

**Date:** 2026-04-16
**Branch:** `phase-c-truthfulness-audit-loop`
**Author:** Wave 1 architecture discoverer (SOLO)
**Predecessor:** Phase B commit `a0a053c`
**Consumers:** 6 Wave 2 implementation agents (n08, n09, n10, n17, latent-wiring, carry-forward)

---

## HALT FINDINGS — Plan vs Reality Contradictions

Discovered while verifying source-of-truth references. Wave 2 agents MUST treat these as authoritative over their plan documents.

### HALT-1 — `RuntimeBlockedError` class does NOT exist in the codebase

**Source claim:** Investigation report Appendix B.3 (and downstream Phase C plan) reference a `RuntimeBlockedError` class in `runtime_verification.py` as the D-02 v2 fail-loud mechanism.

**Reality:** Grep across `src/agent_team_v15/` returns ZERO matches for `RuntimeBlockedError`. The actual D-02 v2 mechanism is:

- `endpoint_prober.py:119` — `infra_missing: bool` field on `DockerContext`, set True at lines 704, 716 only when host genuinely lacks Docker / compose
- `runtime_verification.py:980, 1008, 1176, 1196` — `health = "blocked"` string assignments
- `wave_executor.py:1841-1856` — decision site: `if docker_ctx.infra_missing: return True, "", []` (skip) else `return False, reason, []` (block)

**Impact on Wave 2:** Latent-wiring agent must NOT search for or create `RuntimeBlockedError`. The skip-vs-block boolean is the contract.

### HALT-2 — All `cli.py` line numbers in plan/investigation docs are stale post-Phase-B

Phase B added ~200 LOC to `cli.py`. Verified current line refs:

| Symbol | Plan line | Actual line |
|---|---|---|
| `_run_audit_loop` def | 5843 | **6050** |
| Production call into `_run_audit_loop` | 4782 | **4989** (gate at 4978) |
| `_run_audit_fix_unified` def | 5605 | **5812** |
| Final `report_path.write_text` | 6033 | **6240** |
| Inside-loop call to `_run_audit_fix_unified` | n/a | **~6158** |
| Recovery paths using `tracking_documents` | varies | **6294, 6461, 6556, 6635, 6713, 6797, 6880, 7021, 7700, 9065** |
| GATE_FINDINGS writers | varies | **11453, 12656** |
| RUNTIME_VERIFICATION.md writer | varies | **12700** |
| Wave B/D builders | n/a | **1778 (B), 1794 (D)** |

**Impact on Wave 2:** All agents MUST re-grep for symbol names rather than trusting line refs from older docs.

### HALT-3 — `wave_executor.py` D-02 site shifted

**Plan claim:** D-02 v2 skip-vs-block at `wave_executor.py:1640-1648`.
**Reality:** Lines 1640-1648 are part of `_run_npm_test`/`_run_jest` test runner, completely unrelated. Actual D-02 v2 skip-vs-block decision is at **`wave_executor.py:1841-1856`**.

### HALT-4 — Phase C plan rev claims 4 carry-forwards, plan body documents 3

The Phase C plan (`docs/plans/2026-04-16-phase-c-plan.md`) header says "Phase B exited with 4 non-HALT findings filed for Phase C" but the body documents 3 (C-CF-1, C-CF-2, C-CF-3). Treating the body as authoritative.

---

## Section 1 — Audit-Loop Call Graph (verifies Investigation Appendix B.2.1)

### Call graph (production milestone path)

```
cli.py:4978   if config.audit_team.enabled:
cli.py:4989       result = _run_audit_loop(...)            <-- production entry
                       │
cli.py:6050            def _run_audit_loop(...):
cli.py:~6080               cycle 1: run auditors → write AUDIT_REPORT.json
cli.py:~6158               if cycle ≥ 2 and verdict != PASS:
                               _run_audit_fix_unified(...)  <-- N-08 gap site
                                   │
cli.py:5812                        def _run_audit_fix_unified(...):
                                       (5812-6047 — NO `tracking_documents` import)
                                       dispatches to fixer agents
                                       returns outcome
cli.py:6240               report_path.write_text(current_report.to_json())
```

### Contract for N-08 wiring (the gap)

**The gap:** `_run_audit_fix_unified` (5812-6047) does NOT import `tracking_documents`. Build-l's `FIX_CYCLE_LOG.md` is 7 lines (header only) despite a non-PASS audit cycle running — empirically confirmed.

**Recovery paths already do this correctly.** Reference pattern at `cli.py:6294, 6461, 6556, 6635, 6713, 6797, 6880, 7021, 7700, 9065`:

```python
from .tracking_documents import (
    initialize_fix_cycle_log,
    build_fix_cycle_entry,
    append_fix_cycle_entry,
    FIX_CYCLE_LOG_INSTRUCTIONS,
)
```

**N-08 fix shape (loop-layer injection — DO NOT touch `_run_audit_fix_unified`):**

1. At entry to `_run_audit_loop` (~6050): import `tracking_documents` + call `initialize_fix_cycle_log(requirements_dir)` if absent.
2. Inside the loop, AFTER each `_run_audit_fix_unified(...)` call (~6158): build entry via `build_fix_cycle_entry(phase="audit-fix", cycle_number=cycle, failures=findings_by_severity, previous_cycles=cycle-1)` and `append_fix_cycle_entry(requirements_dir, entry)`.
3. `append_fix_cycle_entry` is idempotent (no-op if entry already in file) — safe across retries.

**Why loop-layer not unified-fix-layer:** keeps `_run_audit_fix_unified` focused on dispatch. Recovery code already proves this layer is the right home for tracking I/O.

### Confidence

**MEDIUM-HIGH** that B.2.1 correction holds:
- ✅ Mechanism confirmed by grep + Read: `_run_audit_fix_unified` lacks tracking imports
- ✅ Build-l empirical confirmation: FIX_CYCLE_LOG.md = header only after non-PASS run
- ⚠️ Line numbers shifted from plan; Wave 2 must re-grep
- ⚠️ Could not run live audit cycle to confirm exact failure mode end-to-end (no smoke in this wave)

---

## Section 2 — Per-Wave-B-Bug Current-Idiom Reference (8 LLM bugs)

All quotes below are **verbatim from context7** — Wave 2 N-09 agent must paste these into Wave B prompt hardeners as the canonical pattern. Source URL preserved for each.

### AUD-009 — Global exception filter must use `APP_FILTER` provider, not `useGlobalFilters` for DI

**Source:** `https://github.com/nestjs/docs.nestjs.com/blob/master/content/exception-filters.md`

> Register a global filter in a module's providers array using APP_FILTER token to enable dependency injection. This approach allows the filter to access module dependencies and is the recommended way to register global filters.

```typescript
import { Module } from '@nestjs/common';
import { APP_FILTER } from '@nestjs/core';

@Module({
  providers: [
    {
      provide: APP_FILTER,
      useClass: HttpExceptionFilter,
    },
  ],
})
export class AppModule {}
```

**Hardener directive:** "When the filter has constructor-injected services (Logger, ConfigService, repositories), use the `APP_FILTER` provider in `app.module.ts`. Reserve `app.useGlobalFilters(new Filter())` in `main.ts` for filters with NO dependencies."

### AUD-010 — `ConfigService.get` returns `undefined`; use `getOrThrow` or default

**Source:** `https://github.com/nestjs/docs.nestjs.com/blob/master/content/techniques/configuration.md`

> Apply a Joi schema to validate environment variables within the NestJS ConfigModule, including setting default values.

```typescript
import * as Joi from 'joi';

@Module({
  imports: [
    ConfigModule.forRoot({
      validationSchema: Joi.object({
        NODE_ENV: Joi.string()
          .valid('development', 'production', 'test', 'provision')
          .default('development'),
        PORT: Joi.number().port().default(3000),
      }),
    }),
  ],
})
export class AppModule {}
```

**Hardener directive:** "Required env vars: use `configService.getOrThrow<T>('KEY')` (throws on missing). Optional with default: `configService.get<T>('KEY', defaultValue)`. NEVER `configService.get('KEY')` without a default — return type is `T | undefined` and TypeScript will not catch null deref."

### AUD-012 — bcrypt is the canonical hashing library for NestJS auth (not bcryptjs)

**Source:** `https://github.com/nestjs/docs.nestjs.com/blob/master/content/security/encryption-hashing.md`

> Illustrates how to hash a password using the `bcrypt` library with a specified number of salt rounds. The `saltOrRounds` parameter determines the computational cost of hashing.

```typescript
import * as bcrypt from 'bcrypt';

const saltOrRounds = 10;
const password = 'random_password';
const hash = await bcrypt.hash(password, saltOrRounds);
```

```typescript
const isMatch = await bcrypt.compare(password, hash);
```

**Hardener directive:** "Use `bcrypt` (native) — not `bcryptjs`. REQUIREMENTS.md:62 lists `bcrypt` explicitly. Salt rounds from `configService.getOrThrow<number>('BCRYPT_ROUNDS')`. Never hardcode rounds."

### AUD-013 — Joi schema validates env vars at boot, not runtime

**Source:** Same as AUD-010 above. Combined with `ConfigModule.forRoot({ validationSchema })`.

**Hardener directive:** "Every env var consumed by the app MUST appear in the Joi schema in `app.module.ts`. The schema MUST `.required()` for non-defaulted secrets (JWT_SECRET, DATABASE_URL) and `.default(...)` for tunables (PORT, BCRYPT_ROUNDS). Boot fails fast on missing required env vars — do not `getOrThrow` at runtime as a substitute for boot-time validation."

### AUD-016 — JWT strategy must extract from `Authorization: Bearer <token>`

**Source:** `https://github.com/nestjs/docs.nestjs.com/blob/master/content/recipes/passport.md`

> Defines the `JwtStrategy` using `passport-jwt` to extract and validate JSON Web Tokens from incoming requests. The `validate` method processes the decoded token payload to return user details.

```typescript
import { ExtractJwt, Strategy } from 'passport-jwt';
import { PassportStrategy } from '@nestjs/passport';
import { Injectable } from '@nestjs/common';
import { jwtConstants } from './constants';

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor() {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      ignoreExpiration: false,
      secretOrKey: jwtConstants.secret,
    });
  }

  async validate(payload: any) {
    return { userId: payload.sub, username: payload.username };
  }
}
```

**Hardener directive:** "JWT extractor MUST be `ExtractJwt.fromAuthHeaderAsBearerToken()`. `ignoreExpiration` MUST be `false`. `secretOrKey` MUST come from `configService.getOrThrow<string>('JWT_SECRET')` — NOT hardcoded constants."

### AUD-018 — `@ApiProperty()` requires explicit `type` for non-primitive arrays/nested DTOs

**Source:** `https://github.com/nestjs/docs.nestjs.com/blob/master/content/openapi/types-and-parameters.md`

> Manually define deeply nested array types using raw type definitions when automatic inference is insufficient.

```typescript
@ApiProperty({
  type: 'array',
  items: {
    type: 'array',
    items: {
      type: 'number',
    },
  },
})
coords: number[][];
```

**Hardener directive:** "For nested DTO fields, `@ApiProperty({ type: () => OtherDto })`. For arrays of DTOs, `@ApiProperty({ type: [OtherDto] })`. Reflection alone does NOT resolve generics — explicit `type` keeps OpenAPI spec correct."

### AUD-020 — `ValidationPipe` MUST be registered globally with `whitelist: true`

**Source:** `https://github.com/nestjs/docs.nestjs.com/blob/master/content/techniques/validation.md`

> Combine whitelist and forbidNonWhitelisted options to reject requests containing properties not defined in the DTO, returning an error instead of silently stripping them.

```typescript
app.useGlobalPipes(
  new ValidationPipe({
    whitelist: true,
    forbidNonWhitelisted: true,
  }),
);
```

> Use `ValidationPipe` with `transform: true` at the method level to automatically transform request payloads to DTO instances.

**Hardener directive:** "Register `ValidationPipe` globally in `main.ts` with `{ whitelist: true, forbidNonWhitelisted: true, transform: true }`. Mass-assignment risk if missing — request bodies bypass DTO contracts otherwise."

### AUD-023 — Prisma migrations MUST use `migrate deploy` in production / CI

**Source:** `https://context7.com/prisma/skills/llms.txt`

> Manage database schema changes using Prisma CLI commands. `prisma migrate dev` is for development, creating and applying migrations, while `prisma migrate deploy` is for production environments.

```bash
# Apply migrations (production/CI)
npx prisma migrate deploy

# Create and apply migration (development)
npx prisma migrate dev
```

**Hardener directive:** "Production / CI / Docker entrypoint MUST run `npx prisma migrate deploy` (no schema diff, no prompts). `prisma migrate dev` is forbidden outside developer workstations — it can drop data. Seed via `prisma db seed` AFTER `migrate deploy` succeeds."

---

## Section 3 — Latent Wiring Insertion Points (D-02, D-09 ×2, D-14 ×4)

### D-02 — Skip-vs-block at `wave_executor.py:1841-1856`

**Current state:** Lives correctly. `if docker_ctx.infra_missing: return True, "", []` skips downstream wave gracefully; otherwise `return False, reason, []` blocks.

**Latent-wiring task:** No edit to this site. Verify the upstream caller propagates `(skip, reason, errors)` correctly to wave-result. Key invariant: skip MUST NOT flip `wave_result.success=False`. **No `RuntimeBlockedError` involved (HALT-1).**

### D-09 — `run_mcp_preflight` (`mcp_servers.py:429-482`) — ZERO callers

**Helper signature:**
```python
def run_mcp_preflight(cwd, config, *, log=None) -> dict
```
Writes `.agent-team/MCP_PREFLIGHT.json`. No-op when `config.v18.mcp_required_servers` is empty.

**Latent-wiring task:** Insert single call at orchestration startup in `cli.py` AFTER config load and BEFORE wave-A dispatch. Suggested anchor: locate `if config.audit_team.enabled` at cli.py:4978 and insert preflight earlier — search for "milestone" loop entry. Wave 2 agent must re-grep, but conceptually:

```python
from .mcp_servers import run_mcp_preflight
preflight = run_mcp_preflight(cwd, config, log=log)
```

### D-09 — `ensure_contract_e2e_fidelity_header` (`mcp_servers.py:485-523`) — ZERO callers

**Helper signature:**
```python
def ensure_contract_e2e_fidelity_header(path: Path, *, contract_engine_available: bool) -> None
```
Idempotent: anchor string `"Verification fidelity:"`. Writes header at top of `CONTRACT_E2E_RESULTS.md` if absent.

**Latent-wiring task:** Locate where `CONTRACT_E2E_RESULTS.md` is written (grep `CONTRACT_E2E_RESULTS`). Add call IMMEDIATELY AFTER each write site, with `contract_engine_available=<runtime probe>`.

### D-14 — Verification fidelity labels on 4 artefacts

**Anchor string:** `"Verification fidelity:"`. **Idempotent** — safe to call multiple times.

**4 writer sites to wire:**

1. `verification.py:1154` — `write_verification_summary` writes `VERIFICATION.md`
2. `cli.py:11453` — first GATE_FINDINGS.json writer
3. `cli.py:12656` — second GATE_FINDINGS.json writer
4. `cli.py:12700` — RUNTIME_VERIFICATION.md writer (after `format_runtime_report`)

**Pattern (assume helper analogous to `ensure_contract_e2e_fidelity_header`):**
```python
ensure_<artefact>_fidelity_header(artefact_path, contract_engine_available=<probe>)
```

If no per-artefact helper exists, latent-wiring agent must factor a tiny `_ensure_fidelity_header(path, label, *, available)` utility and call it at all 4 sites.

---

## Section 4 — N-17 Context7 Query Set Per Milestone Template

**Architectural constraint (verbatim from `agents.py:5287-5290`):**

> Firecrawl and Context7 MCP tools are NOT included here because MCP servers are only available at the orchestrator level and are not propagated to sub-agents.

**Therefore N-17 implements orchestrator-side pre-fetch (Fix A).** Sub-agents receive doc snippets as inline prompt text, never as live MCP calls.

**Insertion point in `cli.py`:** Wave B builder dispatch is at **`cli.py:1778`** (`build_wave_b_prompt`); Wave D at **`cli.py:1794`** (`build_wave_d_prompt`). Pre-fetch BEFORE the `builder(...)` call and pass results via a new kwarg `mcp_doc_context`.

**Pre-fetch dict (Wave 2 agent paste verbatim):**

```python
# In cli.py, before Wave B/D dispatch
MCP_DOC_QUERIES_BY_WAVE = {
    "B": [
        ("/nestjs/docs.nestjs.com",
         "global exception filter APP_FILTER provider vs useGlobalFilters"),
        ("/nestjs/docs.nestjs.com",
         "ConfigService getOrThrow vs get and Joi validationSchema env vars"),
        ("/nestjs/docs.nestjs.com",
         "JwtStrategy passport ExtractJwt fromAuthHeaderAsBearerToken"),
        ("/nestjs/docs.nestjs.com",
         "ValidationPipe whitelist forbidNonWhitelisted transform global pipe"),
        ("/nestjs/docs.nestjs.com",
         "ApiProperty type for nested DTO and array of objects"),
        ("/nestjs/docs.nestjs.com",
         "bcrypt hash compare salt rounds password"),
        ("/prisma/skills",
         "prisma migrate deploy production vs migrate dev and db seed"),
    ],
    "D": [
        ("/vercel/next.js",
         "App Router server components data fetching cache"),
        ("/vercel/next.js",
         "next.config.mjs i18n locales rtl rewrites"),
        ("/nestjs/docs.nestjs.com",
         "OpenAPI swagger setup SwaggerModule createDocument"),
    ],
}

def _prefetch_mcp_doc_context(wave: str, mcp_client) -> str:
    """Synchronous pre-fetch; concatenates verbatim quotes for inline prompt."""
    chunks = []
    for lib_id, query in MCP_DOC_QUERIES_BY_WAVE.get(wave, []):
        result = mcp_client.query_docs(libraryId=lib_id, query=query)
        chunks.append(f"### {lib_id} — {query}\n\n{result}\n")
    return "\n---\n".join(chunks)
```

**Then in `build_wave_b_prompt` / `build_wave_d_prompt` signatures:** add `mcp_doc_context: str = ""` kwarg; embed under a clearly labelled "## Canonical framework idioms (verbatim from official docs)" section so the sub-agent sees them as authoritative.

**Failure mode:** if MCP unavailable at orchestrator (which violates current platform assumption), `_prefetch_mcp_doc_context` returns "" and prompt continues without doc block — wave proceeds, no halt.

---

## Section 5 — N-10 Forbidden_Content Scanner Design

**Decision: regex, NOT AST.**

**Rationale:** Patterns are surface-level lexical (TODO/FIXME comments, stub bodies, placeholder strings, untranslated non-ASCII). AST adds TypeScript parser dependency + slow walk over apps/api + apps/web for zero semantic gain. Reserve AST for future structural auditors.

**New module:** `src/agent_team_v15/forbidden_content_scanner.py`

**API:**
```python
@dataclass
class ForbiddenContentRule:
    rule_id: str
    pattern: str           # regex, compiled per scan
    severity: str          # "MAJOR" | "MINOR"
    category: str          # "quality"
    glob: str              # file extension filter, e.g. "**/*.{ts,tsx}"
    message: str
    exclude_paths: list[str] = field(default_factory=list)

def scan_repository(repo_root: Path, rules: list[ForbiddenContentRule]) -> list[AuditFinding]
```

**Default rule set:**

| rule_id | pattern (regex) | severity | glob |
|---|---|---|---|
| FC-001-stub-throw | `throw\s+new\s+Error\(['"](not implemented\|todo\|placeholder\|unimplemented)` | MAJOR | `**/*.{ts,tsx,js,jsx}` |
| FC-002-todo-comment | `\/\/\s*(TODO\|FIXME\|XXX)\b` | MINOR | `**/*.{ts,tsx,js,jsx}` |
| FC-003-block-todo | `\/\*[\s\S]*?(TODO\|FIXME\|XXX)[\s\S]*?\*\/` | MINOR | `**/*.{ts,tsx}` (multiline) |
| FC-004-placeholder-secret | `['"](CHANGE_ME\|YOUR_API_KEY\|REPLACE_ME\|PLACEHOLDER)['"]` | MAJOR | `**/*.{ts,env*}` |
| FC-005-untranslated-rtl | `[\u0600-\u06FF\u0750-\u077F]+` | MINOR | `apps/web/**/*.{ts,tsx}` (excludes `**/i18n/**`) |
| FC-006-empty-fn | `(async\s+)?[a-zA-Z_$][\w$]*\s*\([^)]*\)\s*\{\s*\}` | MINOR | `**/*.{ts,tsx}` |

**Wiring into auditor team:**

- New auditor name: `forbidden_content`
- Invoke AFTER structural auditors in `_run_audit_loop`'s auditor dispatch list
- Findings appended to existing `AUDIT_REPORT.json` `findings[]` array, category=`quality`
- Each finding: `{id, category="quality", severity, file, line, description, remediation, source_finding_ids: []}`
- Emit via `AuditFinding(...)` directly — leverages C-CF-1's evidence fold once shipped

**Excludes:** `node_modules/**`, `dist/**`, `**/*.spec.ts`, `**/*.test.ts`, `**/migrations/**`, `**/i18n/**` (translation source files).

**Test plan:** unit tests per rule with positive + negative fixtures; integration test against build-l artefacts (expect non-zero MAJOR findings on stub auth modules).

---

## Section 6 — Carry-Forward Scope Map

### C-CF-1 — `AuditFinding.from_dict` evidence fold (`audit_models.py:83-104`)

**Current code (lines 83-104):**
```python
@classmethod
def from_dict(cls, data: dict) -> AuditFinding:
    finding_id = data.get("finding_id") or data.get("id") or ""
    return cls(
        finding_id=finding_id,
        auditor=data.get("auditor", "scorer"),
        ...
        evidence=data.get("evidence", []),    # <-- empty when scorer emits file/description
        ...
        cascade_count=int(data.get("cascade_count", 0) or 0),
        cascaded_from=list(data.get("cascaded_from", []) or []),
    )
```

**Empirical confirmation:** Build-l `AUDIT_REPORT.json` first finding keys = `['category', 'description', 'file', 'id', 'line', 'remediation', 'severity', 'source_finding_ids', 'title']`. **NO `evidence` key.** All 28 findings hit this shape — N-11 cascade therefore collapsed 28→28 (zero).

**Fix shape (~10 LOC):**
```python
evidence_list = data.get("evidence", [])
if not evidence_list:
    file_hint = data.get("file")
    desc_hint = data.get("description") or ""
    if file_hint:
        evidence_list = [f"{file_hint} — {desc_hint[:80]}"] if desc_hint else [str(file_hint)]
```

**Tests required (4):**
1. Canonical shape with explicit `evidence[]` — unchanged behavior
2. Scorer shape with `file` + `description` — evidence synthesized as `"<file> — <desc[:80]>"`
3. Scorer shape with `file` only (no description) — evidence = `[str(file)]`
4. Replay against build-l's `AUDIT_REPORT.json` — `len(evidence) > 0` for all 28 findings

### C-CF-2 — 8 missing scaffold-owned paths (`scaffold_runner.py`)

**Current emission gaps:**
- `_scaffold_root_files` (line 754) emits 5 files. **MISSING:** `turbo.json`
- `_scaffold_api_foundation` (line 786) emits 6 files. **MISSING:** `nest-cli.json`, `tsconfig.build.json`, 5 module stubs (`auth/users/projects/tasks/comments/<name>.module.ts`)

**Authoritative content from REQUIREMENTS.md:**

`apps/api/nest-cli.json` (REQUIREMENTS.md:124-133):
```json
{
  "collection": "@nestjs/schematics",
  "sourceRoot": "src",
  "compilerOptions": {
    "plugins": ["@nestjs/swagger"]
  }
}
```

`apps/api/tsconfig.build.json` (standard NestJS — derive from existing `tsconfig.json`):
```json
{
  "extends": "./tsconfig.json",
  "exclude": ["node_modules", "test", "dist", "**/*spec.ts"]
}
```

Per-module stub template (parameterized by `feature_name`):
```typescript
import { Module } from '@nestjs/common';

@Module({
  imports: [],
  controllers: [],
  providers: [],
  exports: [],
})
export class <PascalCase>Module {}
```

Modules emitted: `auth`, `users`, `projects`, `tasks`, `comments` (REQUIREMENTS.md:520-524). Path: `apps/api/src/modules/<name>/<name>.module.ts` (use `ScaffoldConfig.modules_path`, default `src/modules`).

`turbo.json` (REQUIREMENTS.md:492 listed; standard pnpm + turbo pipeline):
```json
{
  "$schema": "https://turbo.build/schema.json",
  "pipeline": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**", ".next/**", "!.next/cache/**"]
    },
    "test": {
      "dependsOn": ["^build"],
      "outputs": []
    },
    "lint": {
      "outputs": []
    }
  }
}
```

**Fix shape (~100 LOC):**
- Add 8 new template helper functions (~12 LOC each):
  - `_scaffold_api_nest_cli_template()`
  - `_scaffold_api_tsconfig_build_template()`
  - `_scaffold_module_stub_template(feature_name: str)` (single helper, parameterized — covers all 5 modules)
  - `_scaffold_root_turbo_template()`
- Extend `_scaffold_api_foundation` (line 786) to write `nest-cli.json`, `tsconfig.build.json`, and loop over `["auth", "users", "projects", "tasks", "comments"]` writing `<modules_path>/<name>/<name>.module.ts`
- Extend `_scaffold_root_files` (line 754) to write `turbo.json`

**Tests required (3+):**
1. Per-template unit test (8 templates → 8 unit tests minimum)
2. Integration test: fresh scaffold → all 8 paths exist
3. Integration test: `ownership_contract_enabled + scaffold_verifier_enabled` BOTH ON → verifier returns PASS on fresh scaffold tree

### C-CF-3 — `build_report` extras propagation (`audit_models.py:742`)

**Current code at line 742-797:** `build_report(...)` rebuilds an `AuditReport` from scratch, dropping the 14+ scorer-side top-level keys that D-07's `from_json` captured onto `extras` at `audit_models.py:342`.

**Trigger:** `_apply_evidence_gating_to_audit_report` at `cli.py:798-853` rebuilds via `build_report(...)` when `config.v18.evidence_mode != "disabled"` AND scope partitioning fires.

**Fix shape (~5 LOC):**
```python
def build_report(..., extras: dict | None = None) -> AuditReport:
    ...
    report = AuditReport(...)
    if extras:
        report.extras = dict(extras)  # mirror N-15's spread-first pattern
    return report
```

Caller in `cli.py:798-853` MUST capture pre-rebuild `extras` and pass through.

**Tests required (2):**
1. `extras` dict round-trips through `build_report`
2. Scope-partitioning rebuild path: scorer-side keys (`verdict`, `health`, `notes`, `category_summary`, `finding_counts`, `deductions_total`, `deductions_capped`, `overall_score`, `threshold_pass`, `auditors_run`, `schema_version`, `generated`, `milestone`, `raw_finding_count`, `deduplicated_finding_count`, `pass_notes`, `summary`, `score_breakdown`, `dod_results`, `by_category`) survive byte-identical through the rebuild.

---

## Section 7 — CLI.py Edit Coordination Map

| Agent | Owned cli.py range | Owned other-file range |
|---|---|---|
| **n08** (audit-loop observability) | 6050-6240 (entire `_run_audit_loop` body) | none |
| **n17** (MCP pre-fetch) | 1740-1810 (Wave A/B/D builder dispatch + new `_prefetch_mcp_doc_context` helper inserted ABOVE this region) | `agents.py` `build_wave_b_prompt` / `build_wave_d_prompt` signatures (add `mcp_doc_context` kwarg) |
| **latent-wiring** | TBD-by-grep for `CONTRACT_E2E_RESULTS` writer + insertion of `run_mcp_preflight` near startup; cli.py:11453, 12656, 12700 (3 fidelity-header anchor sites) | `wave_executor.py:1841-1856` (verify only, no edit), `verification.py:1154` (1 fidelity-header site), `mcp_servers.py:429+485` (helpers — NO EDIT, just consumers) |
| **carry-forward** (C-CF-1+2+3) | 798-853 (capture extras pre-rebuild, pass through) | `audit_models.py:83-104` (C-CF-1), `audit_models.py:742-797` (C-CF-3), `scaffold_runner.py:754, 786, 1776+` (C-CF-2 templates + emitters) |
| **n09** (Wave B prompt hardeners) | none | `codex_prompts.py:10-68` (preamble/suffix), `agents.py:7909+` (`build_wave_b_prompt` body) |
| **n10** (forbidden_content scanner) | TBD-by-grep for auditor dispatch list inside `_run_audit_loop` (single line addition) | NEW: `forbidden_content_scanner.py` |

**Conflict-free invariant:** No two agents touch overlapping line ranges. n08 owns 6050-6240 exclusively. n17 owns 1740-1810. carry-forward owns 798-853. Latent-wiring owns 11453, 12656, 12700 (3 distinct insertion points). n10's single-line auditor dispatch addition is in a different region than all the above.

**Coordination requirement:** Each Wave 2 agent MUST `git pull --rebase` before push. If any two agents land in same hour, second to land must rebase (likely zero conflicts given exclusive ranges).

---

## Section 8 — Risk Map (per Wave 2 agent)

### n08 (audit-loop observability)
- **Risk:** Adding `tracking_documents` import at top of cli.py module scope vs inside `_run_audit_loop` — module-scope risks circular import (tracking_documents already imports from cli). **Mitigation:** import INSIDE `_run_audit_loop` (matches recovery pattern at 6294, 6461, etc.).
- **Risk:** `append_fix_cycle_entry` is idempotent on identical entries but NOT on cycle increments. **Mitigation:** ensure entry distinct per cycle (cycle_number is part of entry hash).

### n09 (Wave B prompt hardeners)
- **Risk:** Hardener text bloats Wave B prompt past model context window. **Mitigation:** quote ≤200 chars per bug × 8 bugs = ~1.6 KB extra, well within budget.
- **Risk:** Hardener directives contradict pre-existing prompt language. **Mitigation:** n09 must read full `CODEX_WAVE_B_PREAMBLE` (codex_prompts.py:10-48) and integrate, not append.

### n10 (forbidden_content scanner)
- **Risk:** False positives in i18n source files. **Mitigation:** explicit `exclude_paths=["**/i18n/**"]` on FC-005-untranslated-rtl.
- **Risk:** Slow scan on monorepo. **Mitigation:** glob-filter per rule, skip `node_modules` / `dist` / `.next`.

### n17 (MCP pre-fetch)
- **Risk:** Sub-agents not stripped from MCP — verbatim comment at agents.py:5287-5290 confirms strip is in place. **Mitigation:** none needed; verify by reading agents.py:5285-5295.
- **Risk:** Pre-fetch synchronous blocks orchestrator. **Mitigation:** ~7 queries × <1s each = ≤10s, acceptable; can parallelize via `asyncio.gather` if needed.
- **Risk:** MCP unavailable at orchestrator → empty doc block. **Mitigation:** prompt continues without; not a halt condition.

### latent-wiring (D-02 + D-09 + D-14)
- **Risk:** `CONTRACT_E2E_RESULTS.md` writer hard to locate. **Mitigation:** `Grep -n "CONTRACT_E2E_RESULTS"` in cli.py + verification.py.
- **Risk:** Fidelity-header insertion at wrong moment (BEFORE write vs AFTER). **Mitigation:** call IMMEDIATELY AFTER each `write_text` to keep semantics that header reflects post-write state.
- **Risk:** Idempotency assumption violated if helper is rewritten. **Mitigation:** unit-test helper called twice on same path → no duplicate header.

### carry-forward (C-CF-1 + C-CF-2 + C-CF-3)
- **Risk:** C-CF-2 contract enabled accidentally during Phase C testing. **Mitigation:** all 6 Phase B flags REMAIN default FALSE through Phase C; only flip in Phase FINAL smoke.
- **Risk:** C-CF-3 `extras` overwrites populated fields when both have same key. **Mitigation:** `extras` should NOT contain the canonical schema fields; if collision detected in tests, scope `extras` to non-canonical keys only.
- **Risk:** C-CF-1 evidence fold breaks N-11 cascade tests that asserted empty evidence. **Mitigation:** review N-11 cascade test fixtures; update assertions to expect synthesized evidence.

---

## Section 9 — Out-of-Scope for Phase C → Phase D

The following are NOT in Phase C scope. Wave 2 agents must NOT expand into them; surface as findings if encountered.

1. **Live paid smoke run validating flags end-to-end** — Phase FINAL.
2. **NEW-10 ClaudeSDKClient bidirectional migration** — Sessions 16.5/17/18.
3. **Bug #20 Codex app-server migration** — separate plan.
4. **N-11 cascade algorithm tuning beyond C-CF-1 unblock** — Phase D.
5. **Truth-score calibration (D-17)** — separate plan.
6. **A-09 wave-scope filter** — separate plan in `2026-04-15-a-09-wave-scope-filter.md`.
7. **C-01 auditor milestone scoping refinements** — separate plan.
8. **Live MCP probe at smoke time** — orchestrator-side pre-fetch is the Fix A scope; deeper MCP integration is Fix B/C territory.
9. **N-08 retry policy tuning** (max-cycles, backoff) — observability first; tuning later.
10. **Full N-17 catalog beyond Wave B/D** — Wave A/C/E pre-fetch deferred until B/D proves the pattern.

---

## Section 10 — Self-Audit

**Coverage check vs team-lead brief:**

| Required deliverable | Status |
|---|---|
| 10-section architecture report | ✅ this document |
| HALT findings at top | ✅ 4 findings (HALT-1..4) |
| Source code MUST NOT be written | ✅ no source code touched |
| context7 verbatim quotes (no paraphrasing) | ✅ Section 2 — 8 bugs covered |
| sequential-thinking used | ✅ 4 thoughts (audit-loop walk, N-10 design, edit map, self-audit) |
| Build-l empirical anchor for B.2.1 | ✅ confirmed FIX_CYCLE_LOG.md = header only + AUDIT_REPORT.json shape |
| 6 Wave 2 agents have non-overlapping scope | ✅ Section 7 |
| All 8 Wave B bugs (AUD-009/-010/-012/-013/-016/-018/-020/-023) | ✅ Section 2 |
| 4 latent-wiring sites (D-02, D-09 ×2, D-14 ×4) | ⚠️ D-14 listed 4 sites but `cli.py:11453` and `12656` are GATE_FINDINGS.json, not VERIFICATION.md — Wave 2 latent-wiring agent must confirm fidelity-header applies to JSON artefacts (likely needs JSON variant of helper) |
| Per-bug current-idiom verbatim refs | ✅ all 8 quoted |

**Confidence ratings:**

| Area | Confidence | Reason |
|---|---|---|
| Audit-loop B.2.1 correction | MEDIUM-HIGH | Mechanism + empirical anchor; lines re-verified |
| C-CF-1 fix shape | HIGH | Build-l shape directly proves gap |
| C-CF-2 fix shape + 8 paths | HIGH | REQUIREMENTS.md authoritative content extracted |
| C-CF-3 fix shape | MEDIUM | Pattern from N-15 mirrors clearly; trigger path narrow |
| N-10 regex-vs-AST decision | MEDIUM | Justified for known patterns; future patterns may need AST |
| N-17 pre-fetch design | MEDIUM-HIGH | Architectural constraint verbatim; insertion site located |
| Latent-wiring D-14 on JSON artefacts | LOW | Fidelity-header was designed for markdown; JSON sites need design refinement |
| HALT-1 (RuntimeBlockedError absence) | HIGH | Grep-confirmed |
| Line-shift HALT-2 | HIGH | Re-verified by grep at every cited symbol |

**Plan assumptions I could NOT verify (Wave 2 must verify):**

1. Exact orchestration-startup site for `run_mcp_preflight` insertion in cli.py
2. Whether `CONTRACT_E2E_RESULTS.md` writer exists in cli.py vs verification.py vs elsewhere
3. Whether D-14 fidelity-header design supports JSON artefacts (`GATE_FINDINGS.json`) or needs a JSON-variant helper
4. Inside-loop call line for `_run_audit_fix_unified` (estimated ~6158; Wave 2 must confirm by reading 6050-6240)
5. Whether Wave A/E pre-fetch is in scope (treated as OOS pending B/D validation)

**Phase C exit criteria from plan:**

- [ ] C-CF-1 closed: from_dict synthesizes evidence; N-11 collapse on build-l 28 → ≤20
- [ ] C-CF-2 closed: 8 paths emit; verifier PASS on fresh scaffold with both flags ON
- [ ] C-CF-3 closed: extras preserved through scope-partitioning rebuild
- [ ] Plus N-08, N-09, N-10, N-17 implementations land
- [ ] Plus D-02, D-09, D-14 latent wirings land
- [ ] Full pytest preserved baseline + new tests passing + zero regressions
- [ ] Phase C report `2026-04-16-phase-c-report.md` (Wave 5 deliverable, separate from this Wave 1 architecture report)
- [ ] Phase C commit on `phase-c-truthfulness-audit-loop`

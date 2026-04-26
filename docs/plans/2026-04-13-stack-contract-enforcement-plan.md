# Stack Contract Enforcement — Stop Wave A from Silently Ignoring the PRD's Stack Choices

> **Target repository:** `C:\Projects\agent-team-v18-codex`
>
> **Final destination in builder repo:** `docs/plans/2026-04-13-stack-contract-enforcement-plan.md`
>
> **Status:** Diagnosed empirically during the 2026-04-13 TaskFlow smoke-test run. Not yet fixed. This is **Bug #9** in the v18 smoke-test discovery sequence (#1 path/cwd, #2 dep-prose, #3 misdiagnosis, #4a/b audit dir + schema, #5 PRD/cwd location, #6 CLAUDECODE, #7 operationId dedupe, #8 OpenAPI scaffold script, **#9 stack contract enforcement**).

## ⚠️ NOTE TO THE IMPLEMENTING AGENT

**Investigate fully before writing code.** This document is a hypothesis backed by one smoke-test run. Before touching any file:

1. **Reproduce the drift.** Run a fresh build of the TaskFlow PRD (`v18 test runs/TASKFLOW_MINI_PRD.md`) at any clean path. After Wave A completes, inspect `<cwd>/.agent-team/artifacts/milestone-1-wave-A.json`. Confirm `files_created` includes `*.entity.ts` files and `database/migrations/*.ts` (TypeORM) instead of `prisma/schema.prisma` (Prisma). Confirm files are at flat `src/` instead of `apps/api/src/`.
2. **Read the Wave A prompt** that's actually sent to the LLM. Find where the Wave A prompt is constructed in `src/agent_team_v15/agents.py` or `src/agent_team_v15/wave_executor.py`. Verify whether it (a) explicitly states the ORM choice, (b) explicitly states the monorepo layout, (c) references the MASTER_PLAN's `Merge-Surfaces` lines. The drift symptom suggests at least one of these is missing or weak.
3. **Search the codebase for any existing stack-validation or stack-contract concept.** Look for `stack`, `tech_stack`, `framework`, `orm`, `monorepo`, `merge_surface`, `validate.*wave` in the source tree. The fix should extend whatever exists, not duplicate it.
4. **Check whether `tech_research.detect_tech_stack()` already produces a structured stack model** that could feed a contract. Read `src/agent_team_v15/tech_research.py` end-to-end — there's likely partial infrastructure already.
5. **Decide if this should live in product_ir.py** (where there's an ongoing redesign per the parallel `2026-04-13-product-ir-integration-redesign-plan.md`) or as its own module. Coordinate with the IR redesign — both touch how stack metadata is modeled.
6. **Read the Wave A telemetry from the failing run** (`v18 test runs/build-c-hardened-clean/.agent-team/telemetry/milestone-1-wave-A.json` or `C:/smoke/clean/.agent-team/telemetry/milestone-1-wave-A.json`). Confirm `provider: claude` (Wave A is hardcoded to Claude per `v18.provider_routing` design).

After investigation, **implement the fix completely**: stack-contract data model, contract derivation, prompt injection, post-wave validator, retry/escalation policy, tests for at least 3 stacks (NestJS+Prisma, Express+Drizzle, Django+SQLAlchemy or similar), and integration verification. **Do not ship a partial fix that only covers NestJS+Prisma** — the whole point of this plan is to make it impossible for Wave A to drift on **any** stack.

If your investigation reveals this plan is wrong (e.g., the existing prompt does enforce Prisma but the LLM is overriding it for a different reason, or there's already a validator that's silently disabled), update this document with corrected findings and stop.

---

## Symptom

For a PRD that explicitly says "Prisma ORM + apps/api+web monorepo", Wave A produces a TypeORM scaffold in flat `src/`, ignoring both choices. Wave B and Wave D then faithfully build on top of that wrong foundation, producing 113 frontend files + 70 backend files that are technically correct relative to Wave A's output but fundamentally violate the spec.

The same drift pattern is expected to recur for any stack pair where one option is "what Claude has seen most often" and the spec asks for the other:

- Express + Drizzle (Claude defaults to Mongoose or Sequelize)
- Fastify + Kysely (Claude defaults to Prisma)
- Django + SQLAlchemy (Claude defaults to Django ORM)
- Spring Boot + jOOQ (Claude defaults to JPA/Hibernate)
- ASP.NET Core + Dapper (Claude defaults to EF Core)
- Vite + React + tRPC (Claude defaults to Next.js + tRPC)
- Remix + Drizzle (Claude defaults to Next.js + Prisma)

This is not a NestJS-specific bug. It's a structural weakness in the Wave A handoff.

## Empirical Evidence (from 2026-04-13 smoke test)

Source: `C:/smoke/clean/.agent-team/`

```
MASTER_PLAN.md  (Phase 1, Claude planner) — CORRECT:
  > Stack: NestJS + Next.js App Router + PostgreSQL + Prisma ORM
  > Merge-Surfaces: apps/api/src/app.module.ts, apps/web/src/app/layout.tsx
  > | User | milestone-1 (schema), milestone-2 (service/controller) | Prisma schema in M1 |

milestones/milestone-1/REQUIREMENTS.md  (Phase 1, Claude planner) — CORRECT:
  - Backend (NestJS + Prisma)
  - Configure Prisma ORM with PostgreSQL connection
  - Define complete Prisma schema for all 4 entities
  - Create initial Prisma migration
  - Create base repository pattern for Prisma access

artifacts/milestone-1-wave-A.json  (Wave A, provider: claude) — DRIFTED:
  files_created:
    - src/database/data-source.ts                          ← TypeORM
    - src/database/migrations/1713052800000-InitialSchema.ts ← TypeORM convention
    - src/database/typeorm.config.ts                        ← TypeORM
    - src/users/user.entity.ts                              ← TypeORM @Entity
    - src/projects/project.entity.ts
    - src/tasks/task.entity.ts
    - src/comments/comment.entity.ts
  → No prisma/schema.prisma
  → No apps/api/ prefix
```

Wave B (Codex) then built 70 files on top of this TypeORM foundation. Wave D (Codex) wrote the frontend into the same flat `src/`, causing a NestJS↔Next.js namespace collision in the same directory.

## Root Cause Analysis — UPDATED with the smoking gun

> **Original hypothesis (now disproven):** Wave A's prompt was "weak" and Claude was defaulting to its prior. **That hypothesis was wrong.** Re-reading Wave A's actual log output reveals Claude *explicitly* said "the framework instructions mandate TypeORM (not Prisma)" — meaning it was reading a hardcoded mandate inside the prompt, not improvising.

### THE actual smoking gun

`src/agent_team_v15/agents.py:1908-1942` defines a hardcoded prompt template `_STACK_INSTRUCTIONS` keyed by language. The TypeScript entry **literally mandates TypeORM** with no awareness of what the PRD said:

```python
_STACK_INSTRUCTIONS: dict[str, str] = {
    "python": (
        "\n[FRAMEWORK INSTRUCTIONS: Python/FastAPI]\n"
        "Dependencies (MUST be in requirements.txt): "
        "fastapi>=0.100.0, uvicorn[standard], sqlalchemy[asyncio]>=2.0, asyncpg, "
        "alembic>=1.12.0, ..."
        "Alembic: Create alembic.ini + alembic/env.py + alembic/versions/. ..."
        "Structure: main.py (uvicorn target), src/models/, src/routes/, src/services/, ..."
    ),
    "typescript": (
        "\n[FRAMEWORK INSTRUCTIONS: TypeScript/NestJS]\n"
        "Dependencies: @nestjs/core, @nestjs/common, @nestjs/platform-express, "
        "@nestjs/typeorm, typeorm, pg, ..."          # ← HARDCODED TypeORM dep
        "Database: ... synchronize: false (NOT conditional on NODE_ENV)."  # ← TypeORM-specific config
        "Structure: src/main.ts, src/app.module.ts, src/auth/, src/health/, src/{domain}/"  # ← flat src/, no apps/
        "Migrations: At least one migration in src/database/migrations/."   # ← TypeORM convention
    ),
    ...
}
```

There is no conditional on what ORM the PRD requested. Every TypeScript build gets TypeORM. Every Python build gets SQLAlchemy. The structure is also hardcoded flat `src/` — no `apps/api+web` support.

Additional reinforcement at `agents.py:1055` (in the global `### Database & Migration Standards (MANDATORY)` block):
```
- TypeScript: Use TypeORM migrations, set synchronize: false (NOT conditional on NODE_ENV)
```

`get_stack_instructions(text)` at `agents.py:1981-1990` looks up the language in this hardcoded dict and injects the block. Called from:
- `agents.py:6288` — milestone-1 / Wave A prompt builder
- `agents.py:7562` — backend / Wave B prompt builder

So Wave A *and* Wave B both receive the hardcoded TypeORM mandate. Wave A obeyed it. Wave B inherited the same prompt and also followed it. Neither agent was drifting — both were correctly following an instruction the V18 builder itself was injecting.

### Three failure modes (corrected)

1. **Hardcoded ORM and layout in `_STACK_INSTRUCTIONS`** *(THE actual root cause)*. The framework-instructions block is not parametrized on the chosen ORM/layout. PRD's stated stack is irrelevant once `_STACK_INSTRUCTIONS["typescript"]` is injected.
2. **No deterministic post-Wave-A validation.** Even if the prompt were fixed, a defensive scanner would have caught Wave A's TypeORM output. The pipeline trusts every wave's output without verifying it conforms to the declared spec.
3. **Stack metadata is descriptive prose, not a machine-readable contract.** The MASTER_PLAN says "Prisma ORM" in plain English. Nothing in the run state programmatically asserts which ORM/layout the build is targeting. Without a structured contract, no scanner can validate against it even if it existed.

The DTO scanner (`DTO-CASE-001`) caught a *symptom* of the drift (Wave A's snake_case `password_hash` and `avatar_url` fields, which TypeORM tolerates but the build's camelCase contract rejected) and forced Wave B to rename them. But the root cause — wrong ORM, wrong layout — was never caught because there's no scanner for it.

### Why the original hypothesis was wrong

I initially assumed Claude was "defaulting to its strongest prior" because of a weak prompt. The empirical evidence (Wave A's own log narration) flat-out contradicts that: Claude *correctly identified* the instructions as mandating TypeORM. It wasn't a model behavior bug. It was a prompt-template content bug. **The fix is much simpler than the original plan suggested.**

## Why This Change Is Needed

Without enforcement, every PRD that picks anything other than the LLM's most-likely-default for the given framework family will silently get the wrong stack. The DTO and integration scanners catch some symptoms after Wave B/E. By then it is far too late — 113 frontend files and 70 backend files are built on the wrong foundation. Cost burned, milestones blocked, audit will at best flag "missing Prisma" as one finding among 50.

Stack drift is the most expensive class of LLM error in this pipeline because it propagates downstream. Every other bug we've found has been local (a path is wrong, an env var is set, a schema field is missing). Stack drift is global — it makes the entire app shape wrong.

## Scope

This plan changes:

- **A new `StackContract` dataclass** that captures the canonical stack as a machine-readable structure
- Stack contract derivation from PRD + MASTER_PLAN + tech_research output
- Wave A prompt builder — explicit, repeated stack-contract injection
- A new **deterministic post-Wave-A validator** that scans `files_created` + content
- Wave A retry / escalation policy when the validator rejects
- Optional defense-in-depth: same validator runs post-Wave-B and post-Wave-D
- Wave executor integration to invoke the validator and route rejections
- Built-in stack contracts for the most common stacks (extensible)
- Tests covering at least 3 stacks
- Telemetry: per-wave `stack_contract_violations` field

This plan does **not** change:

- The wave pipeline structure (still A → B → C → D → D.5 → T → E → audit)
- Provider routing (Wave A still Claude, Wave B/D still Codex)
- The Schema Handoff format (purely additive — new stack contract is layered on top)
- The audit team's role (it audits *after*; this plan stops bad output *during*)

## Non-Goals

1. Do not rewrite the Wave A prompt from scratch. Inject the stack contract; do not redesign the wave's responsibilities.
2. Do not block builds when the validator detects a soft drift (e.g., a single import that uses `@nestjs/typeorm` while the rest is Prisma). Hard-block only when ≥1 disqualifying file is created (e.g., `*.entity.ts` decorated with `@Entity` when ORM=Prisma).
3. Do not implement stack contracts for niche or hypothetical stacks. Ship the 6-8 most common (listed below). The data model must be extensible enough that adding a new contract is an isolated patch.
4. Do not require the user to write a stack contract by hand. The contract must be auto-derived from PRD signals + tech_research detection. Manual override available but optional.
5. Do not change the PRD format or require users to add `stack:` blocks. The existing prose-based stack mention is sufficient input.

## Code Map — UPDATED with verified line numbers

| File | Lines | Role |
|---|---|---|
| **`src/agent_team_v15/agents.py`** | **1908-1942** | **`_STACK_INSTRUCTIONS` dict — THE smoking gun.** Hardcoded ORM mandates per language. This is the file you must change for the primary fix |
| `src/agent_team_v15/agents.py` | 1981-1990 | `get_stack_instructions(text)` — looks up the language in the dict. Add ORM/layout params here |
| `src/agent_team_v15/agents.py` | 6288 | Call site: milestone-1 / Wave A prompt builder injects the block |
| `src/agent_team_v15/agents.py` | 7562 | Call site: backend / Wave B prompt builder injects the block |
| `src/agent_team_v15/agents.py` | 1055 | Secondary mandate: global "Database & Migration Standards" block reinforces "TypeScript: Use TypeORM migrations" — also needs parametrization |
| `src/agent_team_v15/wave_executor.py` | search for `run_wave_compile_check` call site | Wave dispatch + telemetry — the optional defensive validator hooks here |
| `src/agent_team_v15/tech_research.py` | `detect_tech_stack()` | Already returns structured stack info — reuse for ORM detection |
| `src/agent_team_v15/product_ir.py` | — | Product IR — coordinate with the parallel IR redesign plan (`2026-04-13-product-ir-integration-redesign-plan.md`); `StackContract` may live here as a new field |
| `src/agent_team_v15/quality_checks.py` | search for `run_dto_contract_scan` | Existing scanner pattern — defensive stack-validator follows the same shape |
| `src/agent_team_v15/state.py` | `RunState` dataclass | Add `stack_contract` field for resume persistence |

## Investigation Checklist — UPDATED (mostly already verified)

The smoking gun is now confirmed; treat these as sanity checks rather than open questions:

- [x] **Confirmed:** `_STACK_INSTRUCTIONS` at agents.py:1908-1942 hardcodes TypeORM for all TypeScript builds
- [x] **Confirmed:** `get_stack_instructions(text)` at agents.py:1981-1990 has no ORM/layout parameters
- [x] **Confirmed:** Called from milestone-1 prompt (agents.py:6288) and backend prompt (agents.py:7562) — both Wave A and Wave B inherit the mandate
- [x] **Confirmed:** Wave A's own log narration says: *"the framework instructions mandate TypeORM (not Prisma)"* — proves the instruction reaches Claude unchanged
- [ ] Verify whether `tech_research.detect_tech_stack()` returns ORM info (Prisma vs TypeORM) as a structured field, or only the framework name. If the latter, the primary fix needs to also extract ORM choice from PRD or MASTER_PLAN
- [ ] Find `RunState` and confirm there's no existing `stack` / `orm` / `framework` field; add one if needed
- [ ] Verify there's no other prompt-injection site that reinforces the wrong ORM (search for `typeorm`, `TypeORM`, `prisma migrate`, `migration:run` in all `.py` files)
- [ ] Confirm `_STACK_INSTRUCTIONS["python"]` similarly hardcodes SQLAlchemy/Alembic and would need parametrization for Python+SQLModel, Python+Tortoise, Python+Django-ORM, etc.
- [ ] Read 3-5 examples of how `quality_checks.run_dto_contract_scan` integrates with the wave engine — replicate that pattern for the new stack-contract scanner
- [ ] Check whether the audit team would currently flag "wrong ORM" — almost certainly not, since auditors are LLM-based and the drift looks "internally consistent"

## Target Design Overview — TWO TIERS

The fix has two tiers, **and the implementing agent must do both**:

- **TIER 1 — PRIMARY FIX (mandatory, ~50 LOC).** Parametrize `_STACK_INSTRUCTIONS` so the framework instructions block adapts to the chosen ORM/layout instead of mandating one. This is the actual root cause and the actual cure. Without this, any other safeguard is just compensating for a bug that's still in the prompt.
- **TIER 2 — DEFENSE-IN-DEPTH SAFEGUARDS (recommended, ~300 LOC).** A `StackContract` data model, a deterministic post-wave validator, telemetry fields, and a retry policy. These exist to catch:
  - Future regressions in `_STACK_INSTRUCTIONS` (someone re-adds a hardcoded mandate)
  - Drift introduced by other prompt fragments not yet known
  - Drift introduced by Codex Wave B even when Wave A is correct
  - Stack mismatches in user-supplied custom prompts

Tier 1 alone fixes today's bug. Tier 2 alone would also fix today's bug (validator catches Wave A's TypeORM output and forces retry), but at higher token cost than Tier 1. **Both tiers together** make the system robust against today's bug AND the next variant of it.

If time/scope is a hard constraint, ship Tier 1 first and Tier 2 in a follow-up PR — but file the follow-up PR before merging Tier 1.

---

### TIER 1 — Parametrize `_STACK_INSTRUCTIONS` (the actual fix)

#### 1.1 Convert `_STACK_INSTRUCTIONS` from dict-of-strings to a function that templates per ORM/layout

In `agents.py`, replace the dict at line 1908-1942 with builder functions:

```python
def _typescript_nestjs_instructions(orm: str, layout: dict[str, str]) -> str:
    """Return framework instructions for NestJS, parametrized on ORM and layout."""
    backend_prefix = layout.get("backend_path_prefix", "")  # e.g. "" or "apps/api/"

    if orm == "prisma":
        deps = (
            "@nestjs/core, @nestjs/common, @nestjs/platform-express, "
            "@prisma/client, prisma, "
            "@nestjs/jwt, @nestjs/passport, passport, passport-jwt, "
            "@nestjs/config, class-validator, class-transformer, @nestjs/swagger"
        )
        db_block = (
            f"Database (Prisma): Define schema in `{backend_prefix}prisma/schema.prisma`. "
            f"Use `prisma migrate dev` for migrations.  Generated client at "
            f"`@prisma/client`. Use `PrismaService` (a custom @Injectable wrapping "
            f"PrismaClient) and inject it.  Do NOT create *.entity.ts files. "
            f"Do NOT use @Entity / @Column / @PrimaryGeneratedColumn — those are "
            f"TypeORM decorators and FORBIDDEN in this project.\n"
        )
        migrations_block = f"Migrations: Prisma migrations live in `{backend_prefix}prisma/migrations/`.\n"
    elif orm == "typeorm":
        deps = (
            "@nestjs/core, @nestjs/common, @nestjs/platform-express, "
            "@nestjs/typeorm, typeorm, pg, "
            "@nestjs/jwt, @nestjs/passport, passport, passport-jwt, "
            "@nestjs/config, class-validator, class-transformer, @nestjs/swagger"
        )
        db_block = (
            "Database (TypeORM): Individual env vars DB_HOST/DB_PORT/DB_USERNAME/DB_PASSWORD/DB_DATABASE. "
            "Set synchronize: false (NOT conditional on NODE_ENV).\n"
        )
        migrations_block = f"Migrations: At least one migration in `{backend_prefix}src/database/migrations/`.\n"
    elif orm == "drizzle":
        deps = (
            "@nestjs/core, @nestjs/common, @nestjs/platform-express, "
            "drizzle-orm, drizzle-kit, pg, "
            "@nestjs/jwt, @nestjs/passport, passport, passport-jwt, "
            "@nestjs/config, class-validator, class-transformer, @nestjs/swagger"
        )
        db_block = (
            f"Database (Drizzle): Define schema in `{backend_prefix}src/db/schema.ts` "
            f"as exported drizzle pgTable() definitions.  Use drizzle-kit for migrations.  "
            f"Inject a `DrizzleService` wrapping the drizzle() instance.  "
            f"Do NOT use @Entity / @Column — those are TypeORM decorators.  "
            f"Do NOT create prisma/schema.prisma — Prisma is forbidden in this project.\n"
        )
        migrations_block = f"Migrations: drizzle-kit generates SQL in `{backend_prefix}drizzle/`.\n"
    else:
        raise ValueError(
            f"Unsupported ORM '{orm}' for NestJS. Supported: prisma, typeorm, drizzle. "
            "Add a branch to _typescript_nestjs_instructions if you need another."
        )

    structure_line = (
        f"Structure: {backend_prefix}src/main.ts, {backend_prefix}src/app.module.ts, "
        f"{backend_prefix}src/auth/, {backend_prefix}src/health/, {backend_prefix}src/{{domain}}/"
    )

    return (
        f"\n[FRAMEWORK INSTRUCTIONS: TypeScript/NestJS + {orm}]\n"
        f"Dependencies: {deps}\n\n"
        f"DI (CRITICAL): Every module using JwtAuthGuard MUST import AuthModule. "
        f"Every @Injectable MUST be in its module's providers. Use proper @Module imports.\n"
        f"{db_block}"
        f"Health: GET /health via HealthController. Register HealthModule in AppModule.\n"
        f"Port: Listen on PORT env var, default 8080: await app.listen(process.env.PORT || 8080).\n"
        f"{structure_line}\n"
        f"Testing: jest + @nestjs/testing + supertest. Minimum 5 .spec.ts files, 20+ test cases.\n"
        f"{migrations_block}"
        f"Redis: Add ioredis for Redis Pub/Sub. Create {backend_prefix}src/events/ module.\n"
        f"CRITICAL: See Section 10 (Serialization Convention Mandate) for MANDATORY "
        f"response interceptor, query param normalization, and request body normalization. "
        f"These MUST be created in the foundation milestone.\n"
    )
```

Mirror the same parametrization for `_STACK_INSTRUCTIONS["python"]`:

```python
def _python_fastapi_instructions(orm: str, layout: dict[str, str]) -> str:
    # Branches: sqlalchemy, sqlmodel, tortoise, django-orm
    ...
```

And add a placeholder pattern for new languages (Go, Rust, Java, etc.).

#### 1.2 Update `get_stack_instructions` to take ORM + layout

```python
def get_stack_instructions(
    text: str,
    orm: str = "",
    layout: dict[str, str] | None = None,
) -> str:
    """
    Detect stacks from text and return combined framework instructions
    parametrized on the chosen ORM and monorepo layout.
    """
    stacks = detect_stack_from_text(text)
    if not stacks:
        return ""
    layout = layout or {"backend_path_prefix": "", "frontend_path_prefix": ""}
    parts: list[str] = []
    for stack in stacks:
        if stack == "typescript":
            parts.append(_typescript_nestjs_instructions(orm or _default_orm_for("nestjs"), layout))
        elif stack == "python":
            parts.append(_python_fastapi_instructions(orm or _default_orm_for("fastapi"), layout))
        elif stack in _STATIC_STACK_INSTRUCTIONS:
            parts.append(_STATIC_STACK_INSTRUCTIONS[stack])  # angular/react remain static
    return "\n".join(parts)


def _default_orm_for(framework: str) -> str:
    """Conservative fallback ORM when none was detected."""
    return {"nestjs": "prisma", "fastapi": "sqlalchemy", "django": "django-orm"}.get(framework, "")
```

The default fallback is deliberately Prisma for NestJS (Prisma is the more common modern default; TypeORM's `@Entity` decorators have a stronger collision risk). Choose conservatively for each framework — when no ORM is specified anywhere, pick the option whose drift cost is lowest.

#### 1.3 Update both call sites in agents.py

```python
# agents.py:6288 (was)
_stack_instr = get_stack_instructions(task)

# agents.py:6288 (now)
_stack_instr = get_stack_instructions(
    task,
    orm=_current_run_state.stack_contract.get("orm", ""),
    layout={
        "backend_path_prefix": _current_run_state.stack_contract.get("backend_path_prefix", ""),
        "frontend_path_prefix": _current_run_state.stack_contract.get("frontend_path_prefix", ""),
    },
)
```

Apply the same change at agents.py:7562.

#### 1.4 Fix the secondary mandate at agents.py:1055

The global "Database & Migration Standards (MANDATORY)" block currently says:
```
- TypeScript: Use TypeORM migrations, set synchronize: false (NOT conditional on NODE_ENV)
```
Replace with ORM-conditional language, or remove the TypeScript-specific bullet (the per-stack instructions already cover it).

#### 1.5 ORM detection — where does `orm` come from?

The `orm` param needs to be sourced from somewhere. Two complementary sources:

1. **PRD parsing** — extend `prd_parser.py` (or `product_ir.py`) to extract a stated ORM from the PRD's stack/tech section. The TaskFlow PRD literally says "Prisma ORM" on line 9 — trivial regex match.
2. **`tech_research.detect_tech_stack()`** — it already detects tech mentions; verify whether ORM names are in its output. If yes, reuse. If no, extend it.

Resolution priority (highest wins):
1. Explicit user override in config (`v18.stack_contract.orm: "prisma"`) — for power users
2. PRD parser explicit match (`"Prisma ORM"`, `"using TypeORM"`, etc.) — most common
3. `tech_research` high-confidence detection
4. Conservative default per `_default_orm_for(framework)` — last-resort safety net

Persist the resolved `orm` (and `layout`) in `RunState.stack_contract` so it survives resume and is visible in STATE.json for debugging.

#### 1.6 Acceptance for Tier 1

A re-run of the 2026-04-13 TaskFlow PRD smoke test (which says "Prisma ORM" in the PRD) must produce:
- `prisma/schema.prisma` (or `apps/api/prisma/schema.prisma` if layout=apps)
- `package.json` with `@prisma/client` and `prisma` in deps, NOT `@nestjs/typeorm` or `typeorm`
- Migration files under `prisma/migrations/`, NOT `src/database/migrations/`
- No `*.entity.ts` files anywhere
- Wave A's log narration must NOT contain "framework instructions mandate TypeORM"

If Tier 1 alone passes that test, the bug is fixed. Tier 2 below is the safety net for next time.

---

### TIER 2 — Defense-in-depth safeguards (recommended)

Tier 2 is the original plan, kept verbatim below as the secondary structure. It builds a `StackContract` data model, a deterministic post-wave validator, telemetry fields, and a one-retry policy. Read it as "what protects us when Tier 1 isn't enough" rather than "the primary fix" — that demotion is the only conceptual change.

### 1. The Stack Contract

A machine-readable contract that captures the canonical choices for one milestone:

```python
@dataclass
class StackContract:
    """Canonical stack choices for a milestone, machine-validatable."""

    backend_framework: str        # "nestjs", "express", "fastify", "django", "fastapi", "spring", "aspnet", ""
    frontend_framework: str       # "nextjs", "remix", "vite-react", "sveltekit", "nuxt", ""
    orm: str                      # "prisma", "typeorm", "drizzle", "kysely", "sqlalchemy", "django-orm", "ef-core", "jpa", ""
    database: str                 # "postgresql", "mysql", "sqlite", "mongodb", ""
    monorepo_layout: str          # "single", "apps", "packages-and-apps", ""
    backend_path_prefix: str      # "" for single, "apps/api/" for apps-style, "backend/" etc.
    frontend_path_prefix: str     # "" for single, "apps/web/" for apps-style, "frontend/" etc.

    # Disqualifying patterns — if Wave A's output matches any of these, REJECT
    forbidden_file_patterns: list[str] = field(default_factory=list)
    forbidden_imports: list[str] = field(default_factory=list)
    forbidden_decorators: list[str] = field(default_factory=list)

    # Required patterns — if Wave A's output is missing all of these, REJECT
    required_file_patterns: list[str] = field(default_factory=list)
    required_imports: list[str] = field(default_factory=list)

    # Provenance — for debugging when the contract is wrong
    derived_from: list[str] = field(default_factory=list)
    confidence: str = "high"  # "explicit" | "high" | "medium" | "low"
```

### 2. Built-in stack contract templates

Ship a registry of known-good contracts. Adding a new stack is one entry:

```python
_BUILTIN_STACK_CONTRACTS = {
    ("nestjs", "prisma"): StackContract(
        backend_framework="nestjs",
        orm="prisma",
        forbidden_file_patterns=[
            r".*\.entity\.ts$",                    # TypeORM convention
            r".*data-source\.ts$",                 # TypeORM convention
            r".*typeorm\.config\.ts$",             # TypeORM convention
        ],
        forbidden_imports=[
            "@nestjs/typeorm", "typeorm",
            "@mikro-orm/core", "@mikro-orm/nestjs",
            "sequelize", "@nestjs/sequelize",
            "mongoose", "@nestjs/mongoose",
        ],
        forbidden_decorators=["@Entity", "@PrimaryGeneratedColumn", "@Column"],
        required_file_patterns=[
            r"prisma/schema\.prisma$",
        ],
        required_imports=["@prisma/client"],
    ),
    ("nestjs", "typeorm"): StackContract(
        backend_framework="nestjs",
        orm="typeorm",
        forbidden_file_patterns=[r"prisma/schema\.prisma$"],
        forbidden_imports=["@prisma/client", "prisma"],
        required_file_patterns=[r".*\.entity\.ts$"],
        required_imports=["@nestjs/typeorm", "typeorm"],
    ),
    ("express", "drizzle"): StackContract(...),
    ("fastify", "prisma"): StackContract(...),
    ("django", "django-orm"): StackContract(...),
    ("django", "sqlalchemy"): StackContract(...),
    ("spring", "jpa"): StackContract(...),
    ("spring", "jooq"): StackContract(...),
    ("aspnet", "ef-core"): StackContract(...),
    ("aspnet", "dapper"): StackContract(...),
    # ... etc — add as smoke tests prove the need
}
```

When `(framework, orm)` doesn't match a builtin, fall back to a synthesized contract built from `tech_research`'s explicit detection (which has a "this was named in the PRD" confidence flag). Use the confidence flag to decide whether validation is hard-blocking or warning-only.

Layout contract (separate dimension, combines with the framework/orm contract):

```python
_BUILTIN_LAYOUT_CONTRACTS = {
    "single": LayoutContract(backend_path_prefix="", frontend_path_prefix=""),
    "apps": LayoutContract(backend_path_prefix="apps/api/", frontend_path_prefix="apps/web/"),
    "packages-and-apps": LayoutContract(...),
    "backend-frontend": LayoutContract(backend_path_prefix="backend/", frontend_path_prefix="frontend/"),
    "client-server": LayoutContract(backend_path_prefix="server/", frontend_path_prefix="client/"),
}
```

### 3. Contract derivation

```python
def derive_stack_contract(
    prd_text: str,
    master_plan_text: str,
    tech_stack: list[TechEntry],
    milestone_requirements: str | None = None,
) -> StackContract:
    """
    Derive the canonical stack contract from PRD + plan + research.
    Confidence ladder:
      - "explicit": all three of (framework, orm, layout) named in PRD/plan
      - "high": ≥2 named, third inferred from tech_research with high confidence
      - "medium": framework named, orm/layout inferred
      - "low": only inferred — emit warning, run validator in advisory mode
    """
```

### 4. Prompt injection (the "you MUST" block)

Add a deterministic, prominent block to the Wave A prompt builder:

```
=== STACK CONTRACT (NON-NEGOTIABLE) ===

You MUST use the following stack for this milestone:

  Backend framework:  {backend_framework}
  Frontend framework: {frontend_framework}
  ORM:                {orm}
  Database:           {database}
  Monorepo layout:    {monorepo_layout}
  Backend path:       {backend_path_prefix}
  Frontend path:      {frontend_path_prefix}

You MUST NOT do any of these:
  - Create files matching: {forbidden_file_patterns}
  - Import from: {forbidden_imports}
  - Use decorators: {forbidden_decorators}

You MUST do all of these:
  - Create at least one file matching: {required_file_patterns}
  - Use at least one import from: {required_imports}

If the milestone REQUIREMENTS file or any other context appears to contradict
this contract, the CONTRACT WINS. Do not improvise — if you cannot satisfy the
contract because the requirements are inconsistent with it, write a single
file `WAVE_A_CONTRACT_CONFLICT.md` explaining the conflict and stop.

A deterministic validator will run on your output. Files outside the contract
will cause the wave to be REJECTED and re-prompted.
```

This block must appear **twice**: once near the top of the prompt (before any flexible context) and once again immediately before the "now write the files" instruction. Repetition combats lost-in-the-middle drift.

### 5. The deterministic post-Wave-A validator

Add to `quality_checks.py` (or a new `stack_validator.py` if cleaner):

```python
@dataclass
class StackViolation:
    code: str               # "STACK-FILE-001", "STACK-IMPORT-001", "STACK-DECORATOR-001", "STACK-MISSING-001"
    severity: str           # "CRITICAL" | "HIGH"
    file_path: str
    line: int
    message: str
    expected: str
    actual: str

def validate_wave_against_stack_contract(
    wave_output: WaveResult,
    contract: StackContract,
    project_root: Path,
) -> list[StackViolation]:
    """
    Deterministic scan of the wave's files_created/files_modified.
    Returns CRITICAL violations for forbidden_file_patterns / forbidden_imports /
    forbidden_decorators. Returns HIGH violation for missing required_file_patterns
    if NO file in the wave matched.
    """
```

Violation codes (extensible):

| Code | Meaning |
|---|---|
| `STACK-FILE-001` | Created a file matching a forbidden pattern (e.g., `*.entity.ts` when ORM=prisma) |
| `STACK-FILE-002` | Did not create any file matching required patterns (e.g., no `prisma/schema.prisma` after the foundation milestone) |
| `STACK-IMPORT-001` | Imported a forbidden module (e.g., `from typeorm`) |
| `STACK-IMPORT-002` | No required import found anywhere in the wave's output |
| `STACK-DECORATOR-001` | Used a forbidden decorator (e.g., `@Entity` when ORM=prisma) |
| `STACK-PATH-001` | Wrote files outside the declared backend/frontend path prefix |

### 6. Wave executor integration & retry policy

In `wave_executor.py`, after Wave A's apparent success but BEFORE writing telemetry:

```python
violations = validate_wave_against_stack_contract(
    wave_output=wave_a_result,
    contract=run_state.stack_contract,
    project_root=Path(cwd),
)
critical = [v for v in violations if v.severity == "CRITICAL"]
if critical:
    if wave_a_attempt < MAX_STACK_RETRY_ATTEMPTS:  # default 1
        # Roll back Wave A's files, re-prompt with violation context appended
        rollback_wave(wave_a_result, project_root)
        retry_prompt = build_wave_a_prompt(...) + "\n\nPRIOR ATTEMPT REJECTED:\n" + format_violations(critical)
        return await execute_wave_a(retry_prompt, ...)  # one retry
    else:
        # Persistent drift — fail the milestone and emit findings
        wave_a_result.success = False
        wave_a_result.error_message = "Stack contract violated after retry"
        write_wave_findings(milestone_id, critical)
        return wave_a_result
```

The same validator should run post-Wave-B and post-Wave-D as defense-in-depth (Wave B might import a forbidden module even if Wave A was correct). Post-Wave-B/D violations are findings (not blocking) since by that point we have real code we don't want to throw away.

### 7. Telemetry

Extend per-wave telemetry JSON (already used for Wave A/B/C/D) with:

```json
{
  ...,
  "stack_contract_violations": [
    {"code": "STACK-FILE-001", "severity": "CRITICAL", ...}
  ],
  "stack_contract_retry_count": 0,
  "stack_contract": {
    "backend_framework": "nestjs",
    "orm": "prisma",
    "layout": "apps",
    "confidence": "explicit"
  }
}
```

This makes drift detectable from telemetry alone, no log-grepping required.

### 8. Run state

Add to `RunState` (in `src/agent_team_v15/state.py`):

```python
@dataclass
class RunState:
    ...
    stack_contract: dict[str, Any] = field(default_factory=dict)  # serialized StackContract
    stack_contract_confidence: str = ""
```

Persist on resume so re-runs use the same contract instead of re-deriving.

## Generic Stack Support Matrix (must work for all of these in v1)

| Framework | ORM/Data | Layout | Notes |
|---|---|---|---|
| NestJS | Prisma | apps/ | The failing case from this run |
| NestJS | TypeORM | apps/ | Also valid — should not flag |
| NestJS | Drizzle | apps/ | Newer pattern, stretch goal |
| Express | Prisma | single | Common |
| Express | Drizzle | single | Common |
| Fastify | Prisma | single | Common |
| Fastify | Kysely | single | Common |
| Django | Django ORM | single | Standard Django |
| Django | SQLAlchemy | single | Async-Django pattern |
| FastAPI | SQLAlchemy | single | Standard FastAPI |
| FastAPI | Tortoise | single | Async ORM |
| Spring Boot | JPA/Hibernate | single | Standard |
| Spring Boot | jOOQ | single | Type-safe SQL |
| ASP.NET Core | EF Core | single | Standard .NET |
| ASP.NET Core | Dapper | single | Lightweight |
| Next.js | Prisma | single | Frontend+API in one |
| Next.js | Drizzle | single | Frontend+API in one |
| Remix | Drizzle | single | Common Remix pattern |

Frontend pairings to support: Next.js, Remix, Vite+React, SvelteKit, Nuxt.

Tests must cover at least 3 framework/ORM pairs from this matrix — pick NestJS+Prisma (the failing case), Express+Drizzle (common alt-stack), and Django+Django-ORM (different ecosystem). If those three pass, the contract model is generic enough.

## Acceptance Criteria

The fix is **complete** only when ALL of these are true:

- [ ] `StackContract` dataclass defined and serializable
- [ ] At least 8 builtin stack contracts (per matrix above) registered
### TIER 1 — must-have (otherwise the actual bug isn't fixed)

- [ ] `_STACK_INSTRUCTIONS` dict at agents.py:1908-1942 replaced with parametrized builder functions (`_typescript_nestjs_instructions(orm, layout)`, `_python_fastapi_instructions(orm, layout)`)
- [ ] `get_stack_instructions(text, orm, layout)` accepts ORM + layout params and routes through the builders
- [ ] Both call sites (agents.py:6288 and agents.py:7562) pass the resolved ORM and layout from RunState
- [ ] Secondary mandate at agents.py:1055 ("TypeScript: Use TypeORM migrations") removed or made ORM-conditional
- [ ] `RunState.stack_contract` field added to state.py with `orm` and layout subfields
- [ ] PRD parser (or product_ir / tech_research) extracts the explicit ORM mention and populates `stack_contract.orm` before Phase 1.5 ends
- [ ] Resolution priority implemented: config override > PRD explicit > tech_research high-confidence > conservative default
- [ ] `_default_orm_for("nestjs")` returns `"prisma"` (chosen because TypeORM's `@Entity` decorators have higher drift cost than Prisma's separate schema file)
- [ ] **Re-running the 2026-04-13 TaskFlow PRD smoke test produces `prisma/schema.prisma`, NOT `*.entity.ts` files**, in Wave A's `files_created`
- [ ] Wave A's log narration must NOT contain "framework instructions mandate TypeORM"
- [ ] Per-language ORM coverage: `_typescript_nestjs_instructions` supports prisma + typeorm + drizzle. `_python_fastapi_instructions` supports sqlalchemy + sqlmodel + tortoise (or document why a subset)
- [ ] Tests verify the dispatch: given (text mentioning NestJS, orm="prisma") → returned block contains `@prisma/client`, NOT `@nestjs/typeorm`
- [ ] Tests verify the inverse: given (text, orm="typeorm") → returned block contains `@nestjs/typeorm`
- [ ] Backwards-compat smoke test: existing PRDs that did NOT specify an ORM continue to build (use the conservative default and don't break)
- [ ] No regression in existing tests

### TIER 2 — defense-in-depth (recommended; ship as separate PR if scope-bound)

- [ ] `StackContract` dataclass defined and serializable
- [ ] At least 8 builtin stack contracts registered (see matrix)
- [ ] `derive_stack_contract()` produces a contract from PRD + master plan + tech_research
- [ ] Wave A prompt builder *additionally* injects the contract block twice (top + bottom) — defense in depth on top of Tier 1's fixed templates
- [ ] `validate_wave_against_stack_contract()` returns `StackViolation` list for known bad outputs
- [ ] Wave executor invokes the validator post-Wave-A; on CRITICAL violations, rolls back + re-prompts ONCE; on persistent failure, marks the wave failed with `stack_contract_violations` populated
- [ ] Same validator runs post-Wave-B and post-Wave-D in advisory mode (writes findings, does not block)
- [ ] Per-wave telemetry includes `stack_contract`, `stack_contract_violations`, `stack_contract_retry_count`
- [ ] Tests cover at least 3 distinct stack pairs (NestJS+Prisma, Express+Drizzle, Django+Django-ORM)
- [ ] Test: contract injected when stack is "explicit" → Wave A respects it
- [ ] Test: contract derived as "low" confidence → validator runs advisory, does not block
- [ ] Test: `WAVE_A_CONTRACT_CONFLICT.md` is honored — when Wave A writes that file, the wave is marked failed with a clear error rather than silently succeeded
- [ ] Test: rollback is clean — files created during a rejected Wave A attempt are removed before retry
- [ ] Documentation: `docs/stack-contracts.md` explains the model + how to add a new contract

## Risk Notes

- **Over-blocking risk.** A too-strict validator could reject correct Wave A output for unusual but valid setups (e.g., NestJS + Prisma + a single legacy `*.entity.ts` for a shared type). Mitigate by:
  - Keeping `forbidden_file_patterns` regex narrow
  - Allowing per-contract whitelist exceptions (e.g., `forbidden_file_patterns_exceptions: list[str]`)
  - Failing closed initially (CRITICAL = block) but exposing a config knob `stack_contract_enforcement: "block" | "warn" | "off"` so users can dial down if a builtin contract is wrong for their case
- **Contract-derivation false confidence.** If `tech_research` has 60% confidence the ORM is Prisma but the PRD actually wanted TypeORM (because the user said "we'll use Postgres" and Prisma is the default), the contract would block correct TypeORM output. Mitigate with the confidence ladder: only "explicit" + "high" trigger hard-block; "medium" + "low" emit warnings.
- **One-retry policy may not be enough.** If Wave A's first attempt produces TypeORM and the second still produces TypeORM (Claude's prior is too strong), we fail the milestone. That's correct behavior — better to fail loudly than to ship a wrong-stack build — but worth flagging in the PR description so the team can decide if the retry budget should be 1, 2, or 3 attempts. Telemetry will reveal the answer empirically.
- **Coupling to the parallel product-IR redesign.** That plan introduces `IntegrationItem`/`IntegrationEvidence`. The stack contract is conceptually similar — same "explicit/high/medium/low" confidence model. Coordinate so both plans use the same `Confidence` enum and provenance pattern. If the IR redesign lands first, build the StackContract on top of its evidence model. If this plan lands first, design the confidence model to be reusable by IR integrations.

## Done When

A fresh `python -m agent_team_v15 --prd <PRD with Prisma in spec> --cwd <clean-dir> --depth exhaustive` build:

1. Phase 1 produces a stack-aware MASTER_PLAN as today
2. Phase 1 *additionally* derives a `StackContract` and writes it to `STATE.json` and `.agent-team/STACK_CONTRACT.json`
3. Wave A receives the contract injected into its prompt
4. Wave A's first-attempt output is scanned. If clean, proceeds. If violated:
   a. files rolled back
   b. one retry with violation context
   c. on persistent violation, milestone marked failed with `stack_contract_violations` in telemetry
5. Re-running the 2026-04-13 TaskFlow PRD produces `prisma/schema.prisma` and `apps/api/`-prefixed paths, not the TypeORM-in-flat-src/ output we got today
6. Re-running with a TypeORM-spec'd PRD also works (different contract, same machinery)
7. All tests green, including the three-stack matrix
8. Documentation file checked in

## Out-of-Scope Follow-Ups (file as separate plans)

- Per-language contracts beyond TypeScript/Python/Java/.NET (e.g., Rust+Axum+SQLx, Go+Echo+sqlc) — extend the registry as smoke tests find new gaps
- Cross-milestone contract evolution (e.g., M1 introduces Prisma, M5 adds Redis pub-sub — contract should grow, not freeze)
- LLM-assisted contract derivation when tech_research confidence is too low (today: prompt; later: a dedicated stack-detection sub-orchestrator)
- Migration helper for users with existing builds on the wrong stack (one-shot script that converts TypeORM → Prisma scaffolding) — separate plan, very different scope

---

## Why this design generalizes (the "perfect fix" claim)

The user asked for a fix that prevents this in **any other build of any type or stack**. Three properties make this generalize:

1. **The contract is data, not code.** Adding a new framework or ORM is one entry in `_BUILTIN_STACK_CONTRACTS`. No code path changes. The builder can support 50 stacks with the same machinery.
2. **The validator is deterministic and pattern-based.** It uses regex on filenames + import-statement scans + decorator scans. These primitives work for TypeScript, Python, Java, C#, Rust, Go — any language with a parseable file structure.
3. **The enforcement loop is closed.** Prompt injection (LLM-side) plus deterministic post-output validation (machine-side) is a defense-in-depth pattern: the prompt nudges the LLM toward correct output, and if it drifts anyway, the validator catches and corrects. Either layer alone is insufficient (prompts get ignored, validators have false negatives); together they cover each other's blind spots.

What this fix does NOT promise:

- It does not stop *all* LLM hallucinations. Codex inventing the `'id'` locale and the Inter `'arabic'` subset are local quality issues that a stack contract can't catch (they're not stack choices, they're hallucinated values).
- It does not validate runtime correctness — only structural shape. A Prisma schema that compiles but has wrong field types will pass the stack validator and need to be caught downstream.
- It does not relieve the audit team of its responsibility to catch business-logic issues. The stack contract validator is a *cheap, fast, deterministic* first line of defense; the audit team is the *expensive, thorough, semantic* second line.

These limits are deliberate. A scope-creeped "perfect" validator would be a new LLM, which would have the same drift problems we're trying to solve. The fix has to be deterministic and narrow to be reliable.

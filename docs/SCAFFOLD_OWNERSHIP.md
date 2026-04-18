# Scaffold Ownership Contract

> Phase B artifact — canonical file-level ownership map for the M1 foundation milestone of the v18 hardened builder pipeline. Ground truth is `REQUIREMENTS.md` "Files to Create" (line 575-647 of build-l preserved spec). Total manifest: **60 files**.
>
> This document is STATIC (checked into git). It is consumed by three sites at runtime (Phase B Wave 2):
> 1. `scaffold_runner.py` (owner=scaffold rows drive emission)
> 2. Wave B prompt (owner=wave-b rows are the claim list)
> 3. Wave D prompt (owner=wave-d rows)
>
> Columns:
> - `path` — canonical path (per REQUIREMENTS, not per current scaffold — drift is called out in `notes`)
> - `owner` — one of `scaffold`, `wave-b`, `wave-d`, `wave-c-generator`
> - `optional` — `true` if milestone acceptance does not require the file
> - `emits_stub` — `true` if the owner writes a placeholder that a later wave populates
> - `audit_expected` — `true` if auditors should flag a finding when the file is absent or malformed
> - `notes` — free text; `DRIFT:` prefix marks a current scaffold_runner mismatch that Phase B reconciliation must resolve
>
> For the reasoning behind these assignments, see `docs/plans/2026-04-16-phase-b-architecture-report.md`.

---

## Root (9 files)

```yaml
- path: package.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Currently emitted by scaffold_runner._root_package_json_template (:538). Workspaces ["apps/*","packages/*"] must match pnpm-workspace.yaml.

- path: pnpm-workspace.yaml
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not currently emitted by _scaffold_root_files. Phase B must add template producing packages: [apps/*, packages/*] per pnpm docs."

- path: turbo.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Required by REQUIREMENTS for orchestrating pnpm -r build/test/lint pipelines."

- path: tsconfig.base.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Must declare baseUrl and paths for workspace package references (per TS monorepo guidance)."

- path: .gitignore
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Currently emitted. Must cover node_modules/, dist/, .next/, .turbo/, generated/, .env.local.

- path: .editorconfig
  owner: scaffold
  optional: true
  emits_stub: false
  audit_expected: false
  notes: "DRIFT: not emitted. Nice-to-have; absence is not a milestone failure."

- path: .nvmrc
  owner: scaffold
  optional: true
  emits_stub: false
  audit_expected: false
  notes: "DRIFT: not emitted. Pins Node LTS version for CI parity."

- path: docker-compose.yml
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: _docker_compose_template (:559) defines postgres ONLY. Phase B must extend to postgres+api+web with healthcheck and depends_on.condition: service_healthy per docker-compose spec. PORT must be 4000 (currently 3001 in scaffold env template at :522)."

- path: .env.example
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: scaffold emits PORT=3001 (_env_example_template :522). REQUIREMENTS says PORT=4000. Reconciliation must fix."
```

## apps/api (28 files)

```yaml
- path: apps/api/package.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Emitted by scaffold. Must list @nestjs/common, @nestjs/core, @nestjs/config, @nestjs/swagger, @prisma/client, class-validator, joi, bcrypt, passport, passport-jwt.

- path: apps/api/nest-cli.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. NestJS CLI expects this for nest build to resolve src entry."

- path: apps/api/tsconfig.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Emitted by scaffold. Must extend ../../tsconfig.base.json.

- path: apps/api/tsconfig.build.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Standard NestJS build config excluding test/."

- path: apps/api/.env.example
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: scaffold emits PORT=3001; REQUIREMENTS says PORT=4000."

- path: apps/api/Dockerfile
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Multi-stage pnpm/node image. Wave B authored because it depends on runtime deps list finalized during Wave B.

- path: apps/api/src/main.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: _api_main_ts_template (:641) uses Number(process.env.PORT ?? 3001) at :677. Must be 4000. Bootstrap pattern follows NestFactory.create(AppModule) + ValidationPipe({whitelist, transform, forbidNonWhitelisted}) per NestJS 11 docs."

- path: apps/api/src/app.module.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: Scaffold emits stub with ConfigModule.forRoot + PrismaModule. Wave B appends business module imports (UsersModule, ProjectsModule, TasksModule, CommentsModule, AuthModule, HealthModule).

- path: apps/api/src/generate-openapi.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: CLI entry that boots AppModule in INIT-only mode and writes openapi.json. Consumed by Wave C generator.

- path: apps/api/src/common/filters/all-exceptions.filter.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Global @Catch() filter translating Prisma errors + HttpException to uniform error envelope.

- path: apps/api/src/common/interceptors/transform-response.interceptor.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Wraps payloads in {data, meta}; respects @SkipResponseTransform().

- path: apps/api/src/common/decorators/public.decorator.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: SetMetadata('isPublic', true) for JwtAuthGuard bypass.

- path: apps/api/src/common/decorators/skip-response-transform.decorator.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: SetMetadata('skipResponseTransform', true) marker.

- path: apps/api/src/common/dto/pagination.dto.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: class-validator DTO with @IsInt @Min(1) page and limit defaults.

- path: apps/api/src/common/dto/uuid-param.dto.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "@IsUUID() id param DTO."

- path: apps/api/src/database/prisma.service.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: scaffold emits at src/prisma/prisma.service.ts (_scaffold_api_foundation :449). REQUIREMENTS canonical path is src/database/prisma.service.ts. Phase B reconciliation moves emission to src/database/."

- path: apps/api/src/database/prisma.module.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: scaffold emits at src/prisma/prisma.module.ts. Must move to src/database/."

- path: apps/api/src/health/health.controller.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: GET /api/health returning {status:'ok'} — M1 acceptance probe.

- path: apps/api/src/health/health.module.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Registers HealthController. Marked @Public().

- path: apps/api/src/modules/auth/auth.module.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "DRIFT: scaffold currently emits at src/auth/ (no modules/ intermediate). REQUIREMENTS path is src/modules/auth/. Empty shell — Wave B populates with JwtStrategy + AuthController in later milestones."

- path: apps/api/src/modules/users/users.module.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "DRIFT: same src/modules/ path mismatch. Empty shell."

- path: apps/api/src/modules/projects/projects.module.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "DRIFT: same src/modules/ path mismatch. Empty shell."

- path: apps/api/src/modules/tasks/tasks.module.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "DRIFT: same src/modules/ path mismatch. Empty shell."

- path: apps/api/src/modules/comments/comments.module.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "DRIFT: same src/modules/ path mismatch. Empty shell."

- path: apps/api/prisma/schema.prisma
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: Scaffold emits skeleton with datasource db (postgresql) + generator client. Wave B extends with domain models in subsequent milestones (M1 only needs the bootstrap). Path is canonical per Prisma docs.

- path: apps/api/prisma/seed.ts
  owner: scaffold
  optional: true
  emits_stub: true
  audit_expected: false
  notes: "DRIFT: not currently emitted. REQUIREMENTS calls for empty skeleton. Optional for M1 acceptance."

- path: apps/api/test/health.e2e-spec.ts
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: supertest against /api/health returning 200 + status:ok. M1 acceptance test.

- path: apps/api/test/jest-e2e.json
  owner: wave-b
  optional: false
  emits_stub: false
  audit_expected: true
  notes: e2e Jest config with rootDir '.', testRegex '.e2e-spec.ts$'.
```

## apps/web (14 files)

```yaml
- path: apps/web/package.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Emitted by scaffold. Must add @hey-api/openapi-ts and @hey-api/client-fetch (currently missing per scaffold_runner :469). next ^15, react ^18, tailwindcss ^3.

- path: apps/web/next.config.mjs
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Required by Next.js 15 app-router. Minimal export {}."

- path: apps/web/tsconfig.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Extends ../../tsconfig.base.json, jsx: preserve, paths for @/* and @taskflow/shared."

- path: apps/web/tailwind.config.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Emitted by scaffold. content globs must cover src/**/*.{ts,tsx}.

- path: apps/web/postcss.config.mjs
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Required for Tailwind processing under Next.js 15."

- path: apps/web/.env.example
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. NEXT_PUBLIC_API_URL, INTERNAL_API_URL per REQUIREMENTS."

- path: apps/web/Dockerfile
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Multi-stage pnpm/node image with next build. Final scaffold emission per plan n06-web-scaffold-impl item 6.

- path: apps/web/openapi-ts.config.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. defineConfig({input: ../api/openapi.json, output: src/lib/api/generated, plugins: ['@hey-api/typescript','@hey-api/sdk','@hey-api/client-fetch']}) per hey-api docs. Consumed by Wave C generator."

- path: apps/web/src/app/layout.tsx
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "Scaffold emits minimal Next.js 15 stub (html + body) — required by app-router. Wave D finalizes with app-specific chrome."

- path: apps/web/src/app/page.tsx
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "Scaffold emits root-route stub. Wave D finalizes with M1 landing content."

- path: apps/web/src/middleware.ts
  owner: scaffold
  optional: false
  emits_stub: true
  audit_expected: true
  notes: "Scaffold emits passthrough stub. Wave D finalizes with JWT cookie forwarding."

- path: apps/web/src/lib/api/client.ts
  owner: wave-d
  optional: false
  emits_stub: true
  audit_expected: true
  notes: Wrapper around generated hey-api client with createClientConfig for baseUrl/auth. Stub for M1.

- path: apps/web/src/test/setup.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted. Imports @testing-library/jest-dom for Vitest."

- path: apps/web/vitest.config.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Emitted by scaffold. environment:'jsdom', setupFiles:['./src/test/setup.ts'].
```

## packages/shared (6 files)

```yaml
- path: packages/shared/package.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: entire packages/shared tree not emitted by scaffold. Spec-defined baseline per M1 REQUIREMENTS — scaffold emits via new _scaffold_packages_shared() method per plan n03-shared-impl."

- path: packages/shared/tsconfig.json
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Extends ../../tsconfig.base.json, composite: true for project references. Scaffold-emitted from fixed template.

- path: packages/shared/src/enums.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "Spec-defined baseline constants per M1 REQUIREMENTS lines 429-432 — UserRole, ProjectStatus, TaskStatus, TaskPriority verbatim. Not derived from Wave B domain modeling."

- path: packages/shared/src/error-codes.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "Spec-defined baseline — 17 ErrorCodes constants per M1 REQUIREMENTS lines 346-364 (VALIDATION_ERROR, UNAUTHORIZED, FORBIDDEN, NOT_FOUND, CONFLICT, INTERNAL_ERROR, PROJECT_NOT_FOUND, PROJECT_FORBIDDEN, TASK_NOT_FOUND, TASK_INVALID_TRANSITION, TASK_TRANSITION_FORBIDDEN, COMMENT_CONTENT_REQUIRED, USER_NOT_FOUND, EMAIL_IN_USE, INVALID_CREDENTIALS, UNAUTHENTICATED, CANNOT_DELETE_SELF). Emitted verbatim by scaffold."

- path: packages/shared/src/pagination.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "Spec-defined baseline — PaginationMeta interface + PaginatedResult<T> class per M1 REQUIREMENTS lines 456-457. Emitted verbatim by scaffold."

- path: packages/shared/src/index.ts
  owner: scaffold
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Barrel re-export of enums/error-codes/pagination. Scaffold-emitted.
```

## packages/api-client (3 files)

```yaml
- path: packages/api-client/package.json
  owner: wave-c-generator
  optional: false
  emits_stub: false
  audit_expected: true
  notes: "DRIFT: not emitted by scaffold. Wave C generator owns — it runs openapi-ts from apps/api/openapi.json."

- path: packages/api-client/tsconfig.json
  owner: wave-c-generator
  optional: false
  emits_stub: false
  audit_expected: true
  notes: Composite project referencing generated output.

- path: packages/api-client/src/index.ts
  owner: wave-c-generator
  optional: false
  emits_stub: true
  audit_expected: true
  notes: Stub barrel — Wave C generator populates during openapi-ts run.
```

---

## Ownership Totals

| Owner | Count |
|---|---|
| scaffold | 44 |
| wave-b | 12 |
| wave-d | 1 |
| wave-c-generator | 3 |
| **Total** | **60** |

Note: `apps/api/src/app.module.ts` and `apps/api/prisma/schema.prisma` are counted under `scaffold` (their primary owner) with `emits_stub: true`; Wave B extends each in later milestones.

`emits_stub: true` breakdown (13 rows total):
- **Scaffold-owned stubs (11)** that Wave B or Wave D later finalize: `apps/api/src/app.module.ts`, `apps/api/prisma/schema.prisma`, `apps/api/src/modules/{auth,users,projects,tasks,comments}/*.module.ts` (5), `apps/api/prisma/seed.ts`, `apps/web/src/app/layout.tsx`, `apps/web/src/app/page.tsx`, `apps/web/src/middleware.ts`.
- **Non-scaffold-owned stubs (2)**: `apps/web/src/lib/api/client.ts` (owner=wave-d; wave-d authors the stub itself), `packages/api-client/src/index.ts` (owner=wave-c-generator; generator populates during openapi-ts run).

## Drift Summary (Phase B Wave 2 must close)

| # | Drift | Canonical | Scaffold emits |
|---|---|---|---|
| DRIFT-1 | src/database/prisma.* | src/database/prisma.{module,service}.ts | src/prisma/prisma.{module,service}.ts |
| DRIFT-2 | src/modules/<name>/<name>.module.ts | src/modules/auth, users, projects, tasks, comments | src/auth, src/users, ... (no modules/ intermediate) |
| DRIFT-3 | PORT=4000 | env.example, main.ts default, joi validator | PORT=3001 (all 3 sites) |
| DRIFT-4 | 6 missing root files | pnpm-workspace.yaml, tsconfig.base.json, turbo.json, docker-compose.yml, .editorconfig, .nvmrc | Not emitted |
| DRIFT-5 | docker-compose full topology | postgres + api + web with healthcheck + depends_on.condition | postgres-only |
| DRIFT-6 | 6 missing apps/web config files | next.config.mjs, tsconfig.json, postcss.config.mjs, openapi-ts.config.ts, .env.example, src/test/setup.ts | Not emitted |
| DRIFT-7 | packages/shared/** | 6 files | Not emitted |
| DRIFT-8 | apps/api/src/generate-openapi.ts | Needs to exist for Wave C | Not emitted |
| DRIFT-9 | apps/api/nest-cli.json + tsconfig.build.json | NestJS CLI expectations | Not emitted |

Nine drift clusters. Closing them is the charter of Phase B Wave 2 implementation agents.

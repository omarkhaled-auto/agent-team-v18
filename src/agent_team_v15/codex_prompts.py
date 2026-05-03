"""Codex prompt wrappers for wave-specialist execution."""

from __future__ import annotations

import re
from typing import Any

from .milestone_scope import MilestoneScope, apply_scope_if_enabled


CODEX_WAVE_B_PREAMBLE = """\
You are an autonomous backend coding agent. You have full access to the
project filesystem. Execute the task below completely and independently.

## Execution Directives

1. **Autonomy** - Explore the codebase freely. Read existing files of the
   same type (services, controllers, modules, DTOs) to understand the
   project's conventions *before* writing any code. Match the patterns,
   naming, and directory layout you discover.

2. **Persistence** - Complete ALL tasks described below. Do not stop early.
   If you encounter an error, debug it and fix it yourself. Do not leave
   TODO comments, placeholder implementations, or no-op stubs.

3. **Codebase conventions** - Before creating a new file, read at least one
   existing file of the same kind in the same directory. Mirror its import
   style, decorator usage, error handling, and export patterns exactly.

4. **Active backend tree only** - If the repository contains multiple backend
   roots or bootstraps, identify the active root from the scaffolded files and
   existing imports, then modify only that tree. Never create a parallel
   ``main.ts``, ``bootstrap()``, or ``AppModule``.

5. **Barrels and proving tests** - If a touched directory already uses an
   ``index.ts`` barrel, update it in the same rollout. Write the minimum
   proving tests for the changed backend surface; Wave T owns exhaustive
   coverage.

6. **Output** - Write finished code directly to disk. Do not wrap output in
   markdown code blocks. Do not run ``git add`` or ``git commit``. Do not
   produce plans, status updates, or summaries - only working code.

7. **No confirmation** - Never ask for clarification or confirmation. Make
   reasonable decisions and keep going.

## Canonical NestJS 11 / Prisma 5 patterns (apply for this wave)

These 9 patterns (AUD-009/010/012/013/016/018/020/023/024) are HARD requirements.
Each block carries the verbatim canonical idiom from upstream docs
(context7-sourced); apply them exactly. Anti-patterns are forbidden even
when they look superficially equivalent.

**AUD-009** - Global exception filters with DI MUST use `APP_FILTER`
provider in a module's providers array, NOT
`app.useGlobalFilters(new Filter())` in main.ts.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/exception-filters.md
- Canonical (verbatim): "Register a global filter in a module's providers
  array using APP_FILTER token to enable dependency injection. This approach
  allows the filter to access module dependencies and is the recommended way
  to register global filters."
- Anti-pattern: `app.useGlobalFilters(new HttpExceptionFilter(logger))` -
  constructor injection silently drops dependencies.
- Positive: `providers: [{ provide: APP_FILTER, useClass: HttpExceptionFilter }]`
  in app.module.ts.

**AUD-010** - For required env keys use
`configService.getOrThrow<T>('KEY')`; for optional keys use
`configService.get<T>('KEY', defaultValue)`. NEVER
`configService.get('KEY')` without a default.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/techniques/configuration.md
- Canonical (verbatim): "Apply a Joi schema to validate environment variables
  within the NestJS ConfigModule, including setting default values."
- Anti-pattern: `const port = configService.get('PORT')` - returns
  `T | undefined`; TypeScript will not catch null deref downstream.
- Positive: `configService.getOrThrow<number>('PORT')` (required) or
  `configService.get<number>('PORT', 3000)` (optional w/ default).

**AUD-012** - Use `bcrypt` (native binding), NOT `bcryptjs`. Salt rounds
MUST be sourced from config
(`configService.getOrThrow<number>('BCRYPT_ROUNDS')`); never hardcode.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/security/encryption-hashing.md
- Canonical (verbatim): "Illustrates how to hash a password using the
  `bcrypt` library with a specified number of salt rounds. The
  `saltOrRounds` parameter determines the computational cost of hashing."
- Anti-pattern: `import * as bcrypt from 'bcryptjs'` or
  `bcrypt.hash(password, 10)` with hardcoded rounds.
- Positive: `import * as bcrypt from 'bcrypt'; const rounds =
  configService.getOrThrow<number>('BCRYPT_ROUNDS'); const hash =
  await bcrypt.hash(password, rounds);`

**AUD-013** - EVERY env var consumed by the app MUST appear in the Joi
`validationSchema` passed to `ConfigModule.forRoot`. Required secrets use
`.required()`; tunables use `.default(...)`. Boot-time validation, not
runtime fallbacks.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/techniques/configuration.md
- Canonical (verbatim): "Apply a Joi schema to validate environment variables
  within the NestJS ConfigModule, including setting default values."
- Anti-pattern: relying on `getOrThrow` at runtime as a substitute for Joi
  schema validation - fails late, not at boot.
- Positive: `Joi.object({ JWT_SECRET: Joi.string().min(16).required(),
  PORT: Joi.number().port().default(3000) })`.

**AUD-016** - JWT strategy MUST extract via
`ExtractJwt.fromAuthHeaderAsBearerToken()`, MUST set
`ignoreExpiration: false`, and MUST source `secretOrKey` from
`configService.getOrThrow<string>('JWT_SECRET')`.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/recipes/passport.md
- Canonical (verbatim): "Defines the `JwtStrategy` using `passport-jwt` to
  extract and validate JSON Web Tokens from incoming requests. The
  `validate` method processes the decoded token payload to return user
  details."
- Anti-pattern: `secretOrKey: 'hardcoded-secret'`,
  `ignoreExpiration: true`, or extracting from cookies/query when the spec
  is Bearer.
- Positive: `super({ jwtFromRequest:
  ExtractJwt.fromAuthHeaderAsBearerToken(), ignoreExpiration: false,
  secretOrKey: configService.getOrThrow<string>('JWT_SECRET') })`.

**AUD-018** - For nested DTOs use `@ApiProperty({ type: () => OtherDto })`;
for arrays of DTOs use `@ApiProperty({ type: [OtherDto] })`. Reflection
alone does NOT resolve generics.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/openapi/types-and-parameters.md
- Canonical (verbatim): "Manually define deeply nested array types using raw
  type definitions when automatic inference is insufficient."
- Anti-pattern: `@ApiProperty({ type: Object })` or omitting `type`
  entirely - OpenAPI spec emits `any`, breaking the typed client generator
  (Wave C).
- Positive: `@ApiProperty({ type: () => AddressDto }) address: AddressDto;`
  or `@ApiProperty({ type: [TagDto] }) tags: TagDto[];`

**AUD-020** - `ValidationPipe` MUST be registered globally in main.ts with
`{ whitelist: true, forbidNonWhitelisted: true, transform: true }`.
- Source: https://github.com/nestjs/docs.nestjs.com/blob/master/content/techniques/validation.md
- Canonical (verbatim): "Combine whitelist and forbidNonWhitelisted options
  to reject requests containing properties not defined in the DTO,
  returning an error instead of silently stripping them."
- Anti-pattern: omitting global registration, or using `whitelist: false` -
  request bodies bypass DTO contracts; mass-assignment risk.
- Positive: `app.useGlobalPipes(new ValidationPipe({ whitelist: true,
  forbidNonWhitelisted: true, transform: true }));`

**AUD-023** - Production / CI / Docker entrypoints MUST run
`npx prisma migrate deploy`. `prisma migrate dev` is FORBIDDEN outside
developer workstations (it can drop data). Seed via `prisma db seed` AFTER
`migrate deploy`.
- Source: https://context7.com/prisma/skills/llms.txt
- Canonical (verbatim): "Manage database schema changes using Prisma CLI
  commands. `prisma migrate dev` is for development, creating and applying
  migrations, while `prisma migrate deploy` is for production environments."
- Anti-pattern: a Dockerfile / CI step / entrypoint script that calls
  `prisma migrate dev` or `prisma db push` against a non-dev database.
- Positive: entrypoint runs `npx prisma migrate deploy && npx prisma db seed
  && node dist/main.js`.

**AUD-024** - NestJS 11 / Express 5 wildcard route strings MUST use named
wildcards. NEVER emit bare `*`, `/*`, `/api/*`, `@Get('users/*')`, or
`forRoutes('*')`.
- Source: https://docs.nestjs.com/migration-guide ; https://expressjs.com/en/guide/migrating-5.html
- Canonical (doc-backed): use `forRoutes('{*splat}')` for middleware that
  must match every route, and named route forms like `/*splat` or
  `/{*splat}` instead of unnamed wildcards.
- Anti-pattern: `consumer.apply(RequestNormalizationMiddleware).forRoutes('*')`
  or `@Get('users/*')` on NestJS 11 / Express 5 - these trigger unsupported
  path warnings and can break runtime routing.
- Positive: `consumer.apply(RequestNormalizationMiddleware).forRoutes('{*splat}')`
  for all-route middleware, or `@Get('users/*splat')` when the route must
  capture trailing segments.

**AUD-025** - On Express 5, `req.query` is getter-backed and MUST NOT be
reassigned. If query normalization is required, mutate the existing query
object in place or derive a local normalized copy without writing back to
`req.query`.
- Source: https://expressjs.com/en/guide/migrating-5.html
- Canonical (verbatim): "The `req.query` property is no longer a writable
  property and is instead a getter."
- Anti-pattern: `req.query = normalizeKeys(req.query)` or
  `req.query = this.normalizeValue(req.query)` in NestJS / Express middleware.
- Positive: `this.normalizeValue(req.query); req.body = this.normalizeValue(req.body);`
  or `const normalizedQuery = normalizeKeys(req.query)` without assigning it
  back to `req.query`.

## Canonical Dockerfile + pnpm patterns (DOCK-001...DOCK-006)

These 6 patterns (DOCK-001/002/003/004/005/006) are HARD requirements for
every Dockerfile and `docker-compose.yml` build entry you write in a pnpm
workspace monorepo. Each block carries the verbatim canonical idiom from
upstream docs (context7-sourced); apply them exactly. Anti-patterns here
are the exact failures observed in prior Wave B runs — do NOT reproduce
them even when they look superficially equivalent.

**DOCK-001** - In a pnpm-workspace monorepo, `build.context` MUST be the
repository root (`.` relative to the compose file) and `build.dockerfile`
MUST be the per-service Dockerfile path relative to that root (e.g.
`apps/web/Dockerfile`). A narrow context like `./apps/web` CANNOT see the
sibling `pnpm-workspace.yaml`, `pnpm-lock.yaml`, or `packages/*/` tree and
will fail `pnpm install` inside the container.
- Source: https://github.com/docker/docs/blob/main/content/reference/compose-file/build.md
- Canonical (verbatim): "`context` defines either a path to a directory
  containing a Dockerfile, or a URL to a Git repository. When the value
  supplied is a relative path, it is interpreted as relative to the project
  directory. Compose warns you about absolute paths used to define the
  build context as those prevent the Compose file from being portable. If
  not set explicitly, `context` defaults to the project directory (`.`)."
- Anti-pattern: `build: { context: ./apps/web, dockerfile: Dockerfile }`
  in a repo whose `pnpm-workspace.yaml` lives at the root — the workspace
  manifest is outside the context and `pnpm install` cannot resolve the
  workspace graph.
- Positive: `build: { context: ., dockerfile: apps/web/Dockerfile }` so
  the Dockerfile sees `pnpm-workspace.yaml`, `pnpm-lock.yaml`, every
  `apps/*/package.json`, and every `packages/*/package.json`.

**DOCK-002** - `COPY <src_dir> .` in a Dockerfile copies the CONTENTS of
`<src_dir>` into WORKDIR; it does NOT create a subdirectory named
`<src_dir>` inside WORKDIR. To preserve the source layout, either copy
into an explicit destination subpath (`COPY <src_dir> ./<src_dir>/`) or
set WORKDIR to the destination BEFORE the COPY.
- Source: https://github.com/docker/docs/blob/main/_vendor/github.com/moby/buildkit/frontend/dockerfile/docs/reference.md
- Canonical (verbatim): "When a directory is specified as a source, its
  contents and filesystem metadata are copied, but the directory itself
  is not. Subdirectories are merged with existing destination directories,
  with conflicts generally resolved in favor of the new content."
- Anti-pattern: `WORKDIR /app` → `COPY apps/web .` → `WORKDIR /app/apps/web`
  → `RUN pnpm next build`. The second WORKDIR lands in an empty directory
  because the previous COPY flattened `apps/web/*` into `/app/`; there is
  no `package.json` at `/app/apps/web/` and the build fails.
- Positive: `WORKDIR /app` → `COPY apps/web apps/web/` → `WORKDIR /app/apps/web`
  → `RUN pnpm next build` preserves the path the WORKDIR expects.

**DOCK-003** - For pnpm workspaces, the `pnpm install` step MUST run from
the directory that contains `pnpm-workspace.yaml` AFTER copying
`pnpm-workspace.yaml`, `pnpm-lock.yaml`, the root `package.json`, every
`packages/*/package.json`, and every `apps/*/package.json` — and BEFORE
copying full sources (so the install layer is cached across source
changes). Use `pnpm install --frozen-lockfile` with the committed
`pnpm-lock.yaml`.
- Source: https://context7.com/pnpm/pnpm/llms.txt
- Canonical (verbatim): "Fetches packages into the virtual store without
  linking them, useful for Docker layer caching. Supports fetching for
  production only and subsequent offline installation."
- Anti-pattern: `COPY apps/web/package.json ./package.json` (using a
  per-app `package.json` as the workspace root) — the committed
  `pnpm-lock.yaml` was resolved against the real workspace root, so the
  lockfile will be rejected or re-resolved and break `--frozen-lockfile`.
- Positive: `COPY .npmrc pnpm-workspace.yaml pnpm-lock.yaml package.json ./` →
  `COPY apps/web/package.json apps/web/` → `COPY packages/shared/package.json
  packages/shared/` → `RUN pnpm install --frozen-lockfile` → finally
  `COPY . .` (or per-directory copies) for the remaining sources.

**DOCK-004** - Multi-stage builds for Next.js / NestJS / TypeScript apps
MUST use at minimum three stages: `deps` (install only), `build`
(compile), `runtime` (thin runtime image). Each later stage uses
`COPY --from=<stage>` to pull ONLY the minimal artifacts it needs.
Never `COPY . .` in the runtime stage — it drags dev dependencies, build
tooling, source, tests, and caches into the shipped image.
- Source: https://github.com/docker/docs/blob/main/content/manuals/build/building/multi-stage.md
- Canonical (verbatim): "This Dockerfile enhances the basic multi-stage
  build by assigning names to each stage using `AS <NAME>`. Naming stages
  improves readability and makes the `COPY --from` instruction more robust
  against future reordering of `FROM` instructions."
- Anti-pattern: a single-stage Dockerfile that ends with dev dependencies,
  TypeScript sources, and the full pnpm store in the final image.
- Positive: `FROM node:20-alpine AS deps` (install) → `FROM node:20-alpine
  AS build` (`COPY --from=deps /app/node_modules ./node_modules`, then
  compile) → `FROM node:20-alpine AS runtime` (`COPY --from=build
  /app/dist ./dist`, plus the minimal `package.json` + production
  `node_modules`), with `CMD ["node", "dist/main.js"]`.

**DOCK-005** - EVERY `COPY` / `ADD` source path MUST resolve INSIDE the
`build.context` directory. Paths that escape the context (`../foo`,
absolute host paths, symlinks out) are sanitized away by BuildKit — the
resulting layer silently omits the file and the subsequent step fails
with `failed to compute cache key: not found` or `file not found`. If a
Dockerfile needs files outside the current context, WIDEN the
`build.context` in `docker-compose.yml`; never try to escape.
- Source: https://github.com/docker/docs/blob/main/_vendor/github.com/moby/buildkit/frontend/dockerfile/docs/reference.md
- Canonical (verbatim): "Local file paths are relative to the build
  context and are identified by the absence of protocol prefixes. To
  maintain security, any paths attempting to navigate outside the build
  context using parent directory notation are automatically sanitized."
- Anti-pattern: `build.context: ./apps/web` plus
  `COPY ../packages/shared/package.json ./packages/shared/` — BuildKit
  strips the `..` and the file is never present in the layer; the build
  dies with `failed to compute cache key`.
- Positive: `build.context: .` at repo root plus
  `COPY packages/shared/package.json ./packages/shared/` from inside
  `apps/web/Dockerfile` (which is now running with the whole repo as
  context).

**DOCK-006** - Never set `WORKDIR <path>` and then immediately run a
command that reads files inside `<path>` unless a prior instruction has
already placed those files at `<path>`. WORKDIR creates the directory if
it does not exist, but it does NOT populate it; if the preceding COPY
did not write into that directory (see DOCK-002), you are running
commands against an empty tree.
- Source: https://github.com/docker/docs/blob/main/_vendor/github.com/moby/buildkit/frontend/dockerfile/docs/reference.md
  (COPY destination and WORKDIR semantics; logical invariant).
- Anti-pattern: `WORKDIR /app/apps/web` → `RUN pnpm next build` without a
  prior `COPY` whose destination is `/app/apps/web/` (or
  `apps/web/`-relative when WORKDIR is `/app`) — there is no
  `package.json` at the current directory, the script cannot resolve
  `next`, and the build fails.
- Positive: `COPY apps/web /app/apps/web/` → `WORKDIR /app/apps/web` →
  `RUN pnpm next build`, or equivalently `WORKDIR /app` →
  `COPY apps/web apps/web/` → `WORKDIR /app/apps/web` →
  `RUN pnpm next build`.

## Pre-scaffolded Infrastructure Contract (AUD-INFRA)

**AUD-INFRA** - If `docker-compose.yml` and `apps/*/Dockerfile` already exist
in the build directory, they are PRE-GENERATED curated infrastructure. You
MUST read them first to understand the container layout (WORKDIRs, ports,
service names, COPY patterns). Your job is to write app code that FITS this
layout. DO NOT restructure the Dockerfiles or rewrite the compose file.
- Source: internal tool template (see `<infrastructure_contract>` block at
  the top of the user prompt when present; it names the exact template
  name + version in use).
- Anti-pattern: Renaming service paths, changing WORKDIR, restructuring
  multi-stage stages, removing .dockerignore entries, inventing a new
  Dockerfile from scratch, or "improving" the layout.
- Positive: Add runtime dependencies to `apps/<svc>/package.json` - the
  Dockerfile already `pnpm install`s the workspace. Add env vars to
  `.env.example` AND the matching `environment:` block in
  `docker-compose.yml`. These two types of edits are expected and welcome.
- If the template cannot express what the app needs, return `BLOCKED: <reason>`
  instead of editing the infrastructure. The human operator can then either
  extend the template upstream or approve your custom Dockerfile for this
  milestone.

## Infrastructure Wiring (Compose + env parity)

The backend service you are building MUST be wired into `docker-compose.yml`
at the repository root. The scaffolder owns that file; respect its canonical
postgres service, credentials, network, and volumes.

- Read the existing `docker-compose.yml` BEFORE writing any compose content.
- If `services.api` already exists, PRESERVE the scaffolder's postgres
  service and credentials exactly as-is. Extend or align the `api` service
  in place; do NOT overwrite or rewrite fields the scaffolder set.
- If `services.api` does NOT exist, ADD it using these canonical fields and
  nothing invented:
    * `build: { context: ./apps/api, dockerfile: Dockerfile }`
    * `ports:` a single entry of the form `"<PORT>:<PORT>"` where `<PORT>`
      is the integer the scaffolder wrote to `services.api.environment.PORT`
      in the existing compose (also matches `PORT=<N>` in `.env.example` and
      the DoD health endpoint in REQUIREMENTS.md). Both sides of the colon
      must be the same literal integer. The scaffolder's env variable is
      named `PORT` — reuse that name, do not invent alternates.
    * `environment` block including `DATABASE_URL` composed from the
      scaffolder's `.env.example` / env template — use the credentials the
      scaffolder already set, never invented values.
    * `depends_on: { postgres: { condition: service_healthy } }`
    * A `healthcheck` block whose test hits the Definition-of-Done health
      endpoint for this milestone (read REQUIREMENTS.md Definition of Done;
      do not guess the path or port).
- Rule: the `api` service entry in `docker-compose.yml` and its
  `apps/api/Dockerfile` MUST both exist or neither does. Shipping a
  Dockerfile without a matching compose entry (or a compose entry without a
  Dockerfile) is a Wave B failure.
- Rule: if the scaffolder already wrote an `api` service, your job is to
  EXTEND or ALIGN it, not to overwrite. Treat the scaffolder's fields as
  canonical.

---

"""

CODEX_WAVE_B_SUFFIX = """

---

## Verification Checklist - Confirm Before Finishing

Before you stop, verify every item below. If any item fails, fix it.

- [ ] Every new module is registered in its parent module's imports array.
- [ ] Every new service is listed in its module's ``providers`` array.
- [ ] Every new controller has proper route and method decorators.
- [ ] Every protected route has the correct auth guard applied.
- [ ] Every DTO class matches the endpoint spec (field names, types, validation).
- [ ] No second ``main.ts``, ``bootstrap()``, ``AppModule``, or parallel backend root was introduced.
- [ ] Touched ``index.ts`` barrels were updated where that directory already uses a barrel.
- [ ] State-machine transitions and Product IR business rules are implemented in code, not comments.
- [ ] All import paths resolve - no broken imports or circular dependencies.
- [ ] No hardcoded secrets, URLs, ports, or magic strings - use config/env.
- [ ] `docker-compose.yml` has an `api` service wired to `apps/api/Dockerfile`; its port, `DATABASE_URL`, `depends_on.postgres.condition: service_healthy`, and healthcheck match the scaffolder-resolved values and the milestone DoD health endpoint. The scaffolder's `postgres` service is untouched.
"""


CODEX_WAVE_D_PREAMBLE = """\
You are an autonomous frontend coding agent. You have full access to the
project filesystem. Execute the task below completely and independently.

## Execution Directives

1. **Autonomy** - Read the generated API client first. Understand every
   exported method, its parameters, and its return types before writing any
   component code.

2. **Persistence** - Complete ALL tasks described below. Do not stop early.
   If a type doesn't match, fix the type - do not cast with ``as any``.

3. **Generated client wins** - Any generic stack instruction that mentions
   ``fetch`` or ``axios`` is superseded by the generated-client rule in the
   shared Wave D prompt. Replace every manual ``fetch`` or ``axios`` call
   with the corresponding typed client method. Do not leave manual HTTP
   calls alongside the generated client.

4. **Ship the feature anyway** - If a generated client export is awkward,
   use the nearest usable generated export and still complete the feature.
   Do not leave a dead-end placeholder screen or a client-gap-only shell.

5. **State completeness** - Every client-backed page must ship with loading,
   error, empty, and success states, and every new user-facing string must be
   added to the project's translation system.

6. **Output** - Write finished code directly to disk. Do not wrap output in
   markdown code blocks. Do not run ``git add`` or ``git commit``.

7. **No confirmation** - Never ask for clarification or confirmation. Make
   reasonable decisions and keep going.

(Note: the rule that ``packages/api-client/*`` is immutable is enforced
in the shared Wave D prompt - it applies to every provider, not just Codex.)

---

"""

CODEX_WAVE_D_SUFFIX = """

---

## Verification Checklist - Confirm Before Finishing

Before you stop, verify every item below. If any item fails, fix it.

- [ ] Zero manual ``fetch()`` or ``axios`` calls remain for endpoints covered
      by the generated client.
- [ ] All generated-client imports resolve without errors.
- [ ] **Zero edits to `packages/api-client/*`** - that directory is the Wave C
      deliverable and is immutable. ``git diff packages/api-client/`` must
      show nothing.
- [ ] Types flow end-to-end from API response to component props - no
      ``as any``, ``as unknown``, or untyped intermediaries.
- [ ] Loading and error states are handled for every client call.
- [ ] No page was left as a client-gap-only shell or dead-end error route.
- [ ] Every client-backed screen has loading, error, empty, and success states.
- [ ] Locale/message registries were updated for every new string.
- [ ] No shadow API layer was added around manual ``fetch`` or ``axios``.
- [ ] No hardcoded API base URLs - the client's configured base is used.
"""


_WAVE_WRAPPERS: dict[str, tuple[str, str]] = {
    "B": (CODEX_WAVE_B_PREAMBLE, CODEX_WAVE_B_SUFFIX),
    "D": (CODEX_WAVE_D_PREAMBLE, CODEX_WAVE_D_SUFFIX),
}


# Native-tool directive prepended to every Codex wave prompt. These tool
# invocations are what emit the ``turn/plan/updated`` and
# ``turn/diff/updated`` notifications the observer's Codex hook listens
# for; shell-based file writes bypass that event stream and starve the
# calibration log. See docs/AGENT_TEAMS_ACTIVATION.md.
CODEX_BOUNDED_RIPGREP_DIRECTIVE = """\
When searching generated, vendor, minified, or dependency JavaScript, or any
file likely to contain very long lines, avoid unbounded ``rg`` output. Use
``rg --max-columns=20000 --max-columns-preview ...`` or an equivalently
bounded excerpt before inspecting matches.
"""

CODEX_LOCKFILE_WRITE_DIRECTIVE = """\
Do not edit dependency lockfiles (``pnpm-lock.yaml``, ``package-lock.json``,
``yarn.lock``, ``bun.lockb``, or equivalent generated lockfiles). Treat them
as host-managed artifacts: change manifests such as ``package.json`` when
needed, then leave lockfile regeneration to the host package-manager step.
"""

CODEX_NATIVE_TOOL_DIRECTIVE = f"""\
<native_tools_contract>
Before doing any work, call ``update_plan`` with the steps you intend to take.
Update the plan (mark inProgress/completed) as you progress.

For every file creation or edit, you MUST use the ``apply_patch`` tool.
ANY shell-based file write is a REJECTED TURN. This includes
``echo ... >``, ``cat <<EOF > file``, ``printf > file``, ``tee``,
``sed -i``, and stdout redirection to any file path inside the project.
These bypass the native change-tracking protocol and are non-compliant.

If you are tempted to run a shell redirection to create or modify a file,
STOP and use ``apply_patch`` instead.

Do not dump full dependency lockfiles or broad recursive file trees into the
turn. In particular, never run full-file reads of ``pnpm-lock.yaml``,
``package-lock.json``, ``yarn.lock``, or equivalent lockfiles just to inspect
dependencies. Use targeted searches, manifest files, and small bounded excerpts
instead. Avoid broad recursive dumps such as unbounded ``Get-ChildItem
-Recurse`` / ``ls -R`` / ``find .`` output; narrow the path and pattern first.

{CODEX_BOUNDED_RIPGREP_DIRECTIVE.strip()}

{CODEX_LOCKFILE_WRITE_DIRECTIVE.strip()}
</native_tools_contract>

"""

_WAVE_B_WRITE_CONTRACT_RE = re.compile(
    r'<codex_wave_b_write_contract files="(?P<count>\d+)">'
)


def _wave_b_wrapper_parts(original_prompt: str) -> tuple[str, str]:
    match = _WAVE_B_WRITE_CONTRACT_RE.search(str(original_prompt or ""))
    if match is None:
        return CODEX_WAVE_B_PREAMBLE, CODEX_WAVE_B_SUFFIX

    count = match.group("count")
    dynamic_preamble = (
        "\n"
        "<tool_persistence>\n"
        "You MUST invoke write-capable tools to produce files to disk. Returning success\n"
        "without file writes is a failure regardless of your reasoning.\n"
        "Exploration-only actions such as read, search, grep, glob, or shell inspection do not\n"
        "count as completion.\n"
        f"Count-based verification: the prompt body names {count} requirements-declared files.\n"
        "Completion is measured by those files existing on disk after your work, not by the\n"
        "shape of your final message.\n"
        "If the scope is blocked, return `BLOCKED: <reason>` instead of a success-shaped summary.\n"
        "</tool_persistence>\n"
        "\n"
        "<infrastructure_milestone_clarification>\n"
        'If REQUIREMENTS.md says "Acceptance Criteria: 0", that means no user-facing acceptance\n'
        "criteria, not zero file production. Infrastructure milestones are completed by producing\n"
        "their declared files and seams.\n"
        "</infrastructure_milestone_clarification>\n"
        "\n"
    )
    dynamic_suffix = (
        "\n"
        "<count_verification>\n"
        f"Before finishing, verify that the {count} requirements-declared files listed in the\n"
        "[DELIVERABLES - ...] block exist on disk. If any are missing, keep writing or return\n"
        "`BLOCKED: <reason>`.\n"
        "</count_verification>\n"
    )
    return CODEX_WAVE_B_PREAMBLE + dynamic_preamble, dynamic_suffix + CODEX_WAVE_B_SUFFIX


def _render_infrastructure_contract_block(
    infra: dict[str, Any] | None,
) -> str:
    """Render the `<infrastructure_contract>` block for Wave B prompts.

    ``infra`` is the stack_contract's ``infrastructure_template`` payload:
        {"name": "pnpm_monorepo", "version": "1.0.0",
         "slots": {"api_service_name": ..., "api_port": ..., ...}}
    Returns the empty string when ``infra`` is None/empty — Wave B prompt
    stays byte-identical to the pre-Issue-14 output in that case.
    """
    if not isinstance(infra, dict) or not infra:
        return ""
    name = str(infra.get("name", "")).strip()
    version = str(infra.get("version", "")).strip()
    slots = infra.get("slots") if isinstance(infra.get("slots"), dict) else {}
    if not name:
        return ""

    api_svc = str(slots.get("api_service_name", "api"))
    web_svc = str(slots.get("web_service_name", "web"))
    api_port = slots.get("api_port", 4000)
    web_port = slots.get("web_port", 3000)
    pg_version = str(slots.get("postgres_version", "16-alpine"))
    pg_port = slots.get("postgres_port", 5432)
    with_redis = bool(slots.get("with_redis", False))

    lines = [
        "<infrastructure_contract>",
        f"Template: {name}-{version}" if version else f"Template: {name}",
        "Services:",
        f"  - {api_svc} (NestJS, port {api_port}, WORKDIR /app/apps/{api_svc})",
        f"  - {web_svc} (Next.js, port {web_port}, WORKDIR /app/apps/{web_svc})",
        f"Database: PostgreSQL {pg_version} (named volume postgres_data, port {pg_port})",
    ]
    if with_redis:
        lines.append("Cache: Redis 7-alpine")
    lines.extend([
        "Package manager: pnpm with workspace",
        "</infrastructure_contract>",
        "",
    ])
    return "\n".join(lines)


def wrap_prompt_for_codex(
    wave_letter: str,
    original_prompt: str,
    *,
    milestone_scope: MilestoneScope | None = None,
    config: Any | None = None,
    stack_contract: Any | None = None,
) -> str:
    """Wrap a wave prompt with Codex-specific execution directives.

    When *milestone_scope* is supplied (and
    ``config.v18.milestone_scope_enforcement`` is on — default true),
    a milestone-scope preamble is prepended to the codex-directives
    wrapper. The scope layer is idempotent; if the caller already
    applied it (e.g. upstream in ``wave_executor``), passing
    ``milestone_scope=None`` here keeps the output identical to the
    pre-fix wrapper (backward compatible).

    *stack_contract* (Issue #14): when provided and carrying an
    ``infrastructure_template`` payload, an ``<infrastructure_contract>``
    block is prepended at the top of the user prompt so Codex knows which
    curated template layout the scaffolder dropped. Absent payload means
    no injection (byte-identical to the pre-Issue-14 wrap output).
    """

    wrapper = _WAVE_WRAPPERS.get(wave_letter.upper())
    if wrapper is None:
        wrapped = CODEX_NATIVE_TOOL_DIRECTIVE + original_prompt
    else:
        if wave_letter.upper() == "B":
            preamble, suffix = _wave_b_wrapper_parts(original_prompt)
        else:
            preamble, suffix = wrapper

        infra_block = ""
        if wave_letter.upper() == "B" and stack_contract is not None:
            if isinstance(stack_contract, dict):
                infra = stack_contract.get("infrastructure_template")
            else:
                infra = getattr(stack_contract, "infrastructure_template", None)
            infra_block = _render_infrastructure_contract_block(infra)

        wrapped = (
            CODEX_NATIVE_TOOL_DIRECTIVE
            + preamble
            + infra_block
            + original_prompt
            + suffix
        )

    if milestone_scope is None:
        return wrapped

    return apply_scope_if_enabled(
        wrapped,
        milestone_scope,
        config,
        wave=wave_letter,
    )

"""Stack-neutral templates for CLAUDE.md and AGENTS.md (Phase G Slice 1d).

Per master Appendix D R8 + prompt-engineering-design.md Appendix C.1, the
generated-project root receives two project-convention documents:

    CLAUDE.md — loaded by Claude Agent SDK when
               `setting_sources=["project"]` is set.
    AGENTS.md — auto-loaded by Codex (no opt-in).

Both carry the 3 canonical invariants plus stack-contract summary, commands,
forbidden patterns, and naming conventions. LOCKED wording
(`_ANTI_BAND_AID_FIX_RULES`, `IMMUTABLE packages/api-client`, the Wave T
`WAVE_T_CORE_PRINCIPLE`) is deliberately NOT duplicated here — those live
only in the Claude/Codex system prompts per Wave 1c §4.4. Duplicating LOCKED
wording into project-convention files would over-constrain Claude and cause
rule contradictions.
"""
from __future__ import annotations

from typing import Any

from .codex_cli import render_project_codex_config_toml

# --- Canonical R8 invariants (3 lines — prompt-engineering-design.md:1816-1820).
# These are project conventions, NOT LOCKED wording.
R8_INVARIANTS: tuple[str, str, str] = (
    "Do NOT create a parallel `main.ts`, `bootstrap()`, or `AppModule`. "
    "A second one is a FAIL.",
    "Do NOT modify `packages/api-client/*` except in Wave C. That directory "
    "is the frozen Wave C deliverable for all other waves.",
    "Do NOT `git commit` or create new branches. The agent team manages commits.",
)

# --- Additional forbidden patterns (project-convention level).
COMMON_FORBIDDEN: tuple[str, ...] = (
    "Never create `.env` files; use `.env.example` + `process.env` at runtime.",
    "Never add a new framework dep without updating ARCHITECTURE.md.",
    "Never use `console.log` in production paths; use the `logger` module.",
)

# --- Commands expected in a NestJS + Next.js stack.
COMMON_COMMANDS: tuple[tuple[str, str], ...] = (
    ("pnpm install", "install deps"),
    ("pnpm build", "full build"),
    ("pnpm test", "run all tests"),
    ("pnpm lint:fix", "autofix ESLint"),
    ("docker compose up", "start local services"),
)


def _stack_line(stack: dict[str, Any] | None, key: str, default: str) -> str:
    if not stack:
        return default
    value = stack.get(key)
    if not value:
        return default
    return str(value)


def _stack_block(stack: dict[str, Any] | None) -> dict[str, str]:
    return {
        "backend": _stack_line(stack, "backend", "NestJS 11 + Prisma 5 + PostgreSQL 16"),
        "frontend": _stack_line(stack, "frontend", "Next.js 15 (app router) + Tailwind 4 + shadcn/ui"),
        "api_client": _stack_line(stack, "api_client", "OpenAPI-generated at `packages/api-client/`"),
        "tests": _stack_line(stack, "tests", "Jest (api), Playwright (web)"),
        "project_name": _stack_line(stack, "project_name", "project"),
    }


def render_claude_md(stack: dict[str, Any] | None = None) -> str:
    """Render CLAUDE.md content (Part 4.6 template)."""
    s = _stack_block(stack)
    inv = R8_INVARIANTS
    forbidden = "\n".join(f"- {p}" for p in COMMON_FORBIDDEN)
    commands = "\n".join(f"- `{cmd}` — {desc}" for cmd, desc in COMMON_COMMANDS)

    return f"""# Claude Code — Project Instructions

## Project Overview
This project is auto-maintained by the V18 agent-team builder. Architectural
details live in `./ARCHITECTURE.md` (cumulative cross-milestone knowledge).

## Stack & conventions
- Backend: {s['backend']}
- Frontend: {s['frontend']}
- API contract: {s['api_client']}
- Tests: {s['tests']}

## Coding standards
- TypeScript strict mode; no `any` without a comment explaining why.
- ESM imports only; relative paths avoided — use `@/` aliases.
- Functions under 80 lines; files under 500 lines.
- Error handling: throw typed errors; never swallow without logging.
- DTOs in `apps/api/src/**/dto/*.dto.ts`; always use class-validator.

## TDD rules
- Every new endpoint → one integration test under `apps/api/test/`.
- Every new page → one Playwright spec under `apps/web/e2e/`.
- No merged changes without passing tests.

## Commands
{commands}

## Forbidden patterns
- **{inv[0]}** (invariant 1)
- **{inv[1]}** (invariant 2)
- **{inv[2]}** (invariant 3)
{forbidden}

## Naming conventions
- Entities: PascalCase singular (`User`, `Task`, not `Users`, `Tasks`).
- Services: `<Entity>Service` in `apps/api/src/<entity>/`.
- Controllers: `<Entity>Controller` in the same folder.
- React components: PascalCase; hooks `useCamelCase`.

> Project architecture details live in ./ARCHITECTURE.md.
"""


def render_agents_md(stack: dict[str, Any] | None = None) -> str:
    """Render AGENTS.md content (Part 4.7 template)."""
    s = _stack_block(stack)
    inv = R8_INVARIANTS

    return f"""# AGENTS.md — {s['project_name']}

## Project Overview
Auto-maintained agent-team project. Architecture lives in ARCHITECTURE.md.

## Code Style
- TypeScript strict mode.
- 2-space indent, 100-column soft limit.
- No inline comments unless the PR description asks for one.
- ESM imports; no CommonJS.
- Relative paths in apply_patch only.

## Testing
- `pnpm test` runs Jest + Playwright.
- Coverage: minimum 80% on changed files.
- Every new endpoint needs an integration test.

## Database
- {s['backend']}
- Migrations via `prisma migrate dev --name <slug>`.
- Never edit a committed migration; create a new one.

## Important Files
- `packages/api-client/` — Wave C generated; immutable.
- `apps/api/src/app.module.ts` — root NestJS module; add new modules here.
- `apps/web/src/app/` — Next.js app router; routes mirror URL paths.
- `ARCHITECTURE.md` — dynamic architectural record; read before adding
  new entities.

## Do Not
- **{inv[0]}** (invariant 1)
- {inv[2]} (invariant 3)
- {inv[1]} (invariant 2)
- Do not add copyright headers.
- Do not inline-comment code; put rationale in commit message.
- Do not guess at intent — retrieve first, ask second, guess last.

<native_tools_contract>
Before doing any work, call `update_plan` with the steps you intend to take.
Update the plan (mark inProgress/completed) as you progress.

For every file creation or edit, you MUST use the `apply_patch` tool.
ANY shell-based file write is a REJECTED TURN. This includes
`echo ... >`, `cat <<EOF > file`, `printf > file`, `tee`,
`sed -i`, and stdout redirection to any file path inside the project.
These bypass the native change-tracking protocol and are non-compliant.

If you are tempted to run a shell redirection to create or modify a file,
STOP and use `apply_patch` instead.
</native_tools_contract>

<dockerfile_checklist>
Before committing any Dockerfile in a pnpm-workspace monorepo:
- build.context is the repo root (.), not a per-app subdirectory.
- build.dockerfile is the per-app path (e.g. apps/web/Dockerfile).
- Every COPY/ADD source resolves INSIDE build.context (no `..`).
- `COPY apps/web apps/web/` preserves structure; `COPY apps/web .` flattens.
- After WORKDIR <path>, files must exist at <path> — COPY into it explicitly.
- pnpm install reads pnpm-workspace.yaml + pnpm-lock.yaml from the context root.
- Use multi-stage builds: deps, build, runtime.

These bars are detailed as DOCK-001..DOCK-006 in Wave B's execution prompt.
</dockerfile_checklist>
"""


def render_codex_config_toml() -> str:
    """Render the .codex/config.toml snippet raising AGENTS.md cap to 64 KiB.

    Per Wave 1c §4.3 / docs/plans/phase-h2a-codex-config-schema.md: Codex's
    default AGENTS.md cap is 32 KiB; the top-level `project_doc_max_bytes`
    key overrides it.
    """
    return render_project_codex_config_toml()


__all__ = [
    "R8_INVARIANTS",
    "COMMON_FORBIDDEN",
    "COMMON_COMMANDS",
    "render_claude_md",
    "render_agents_md",
    "render_codex_config_toml",
]

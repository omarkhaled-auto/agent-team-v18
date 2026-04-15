"""Codex prompt wrappers for wave-specialist execution."""

from __future__ import annotations

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


def wrap_prompt_for_codex(
    wave_letter: str,
    original_prompt: str,
    *,
    milestone_scope: MilestoneScope | None = None,
    config: Any | None = None,
) -> str:
    """Wrap a wave prompt with Codex-specific execution directives.

    When *milestone_scope* is supplied (and
    ``config.v18.milestone_scope_enforcement`` is on — default true),
    a milestone-scope preamble is prepended to the codex-directives
    wrapper. The scope layer is idempotent; if the caller already
    applied it (e.g. upstream in ``wave_executor``), passing
    ``milestone_scope=None`` here keeps the output identical to the
    pre-fix wrapper (backward compatible).
    """

    wrapper = _WAVE_WRAPPERS.get(wave_letter.upper())
    if wrapper is None:
        wrapped = original_prompt
    else:
        preamble, suffix = wrapper
        wrapped = preamble + original_prompt + suffix

    if milestone_scope is None:
        return wrapped

    return apply_scope_if_enabled(
        wrapped,
        milestone_scope,
        config,
        wave=wave_letter,
    )

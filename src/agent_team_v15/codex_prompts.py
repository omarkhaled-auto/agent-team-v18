"""Codex Prompt Wrappers — Codex-native prompt adaptation.

Wraps wave prompts with directives optimized for Codex's autonomous
execution model.  The original prompt is preserved in full; a preamble
and suffix are added around it so that Codex behaves like a persistent,
self-directed coding agent rather than a chatbot.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Wave B — Backend integration wiring
# ---------------------------------------------------------------------------

CODEX_WAVE_B_PREAMBLE = """\
You are an autonomous backend coding agent.  You have full access to the
project filesystem.  Execute the task below completely and independently.

## Execution Directives

1. **Autonomy** — Explore the codebase freely.  Read existing files of the
   same type (services, controllers, modules, DTOs) to understand the
   project's conventions *before* writing any code.  Match the patterns,
   naming, and directory layout you discover.

2. **Persistence** — Complete ALL tasks described below.  Do not stop early.
   If you encounter an error, debug it and fix it yourself.  Do not leave
   TODO comments, placeholder implementations, or no-op stubs.

3. **Codebase conventions** — Before creating a new file, read at least one
   existing file of the same kind in the same directory.  Mirror its import
   style, decorator usage, error handling, and export patterns exactly.

4. **Output** — Write finished code directly to disk.  Do not wrap output in
   markdown code blocks.  Do not run ``git add`` or ``git commit``.  Do not
   produce plans, status updates, or summaries — only working code.

5. **No confirmation** — Never ask for clarification or confirmation.  Make
   reasonable decisions and keep going.

---

"""

CODEX_WAVE_B_SUFFIX = """

---

## Verification Checklist — Confirm Before Finishing

Before you stop, verify every item below.  If any item fails, fix it.

- [ ] Every new module is registered in its parent module's imports array.
- [ ] Every new service is listed in its module's ``providers`` array.
- [ ] Every new controller has proper route and method decorators.
- [ ] Every protected route has the correct auth guard applied.
- [ ] Every DTO class matches the endpoint spec (field names, types, validation).
- [ ] All import paths resolve — no broken imports or circular dependencies.
- [ ] No hardcoded secrets, URLs, ports, or magic strings — use config/env.
"""

# ---------------------------------------------------------------------------
# Wave D — Frontend client wiring
# ---------------------------------------------------------------------------

CODEX_WAVE_D_PREAMBLE = """\
You are an autonomous frontend coding agent.  You have full access to the
project filesystem.  Execute the task below completely and independently.

## Execution Directives

1. **Autonomy** — Read the generated API client first.  Understand every
   exported method, its parameters, and its return types before writing any
   component code.

2. **Persistence** — Complete ALL tasks described below.  Do not stop early.
   If a type doesn't match, fix the type — do not cast with ``as any``.

3. **Replace, don't wrap** — Replace every manual ``fetch`` or ``axios``
   call with the corresponding typed client method.  Do not leave manual
   HTTP calls alongside the generated client.

4. **Output** — Write finished code directly to disk.  Do not wrap output in
   markdown code blocks.  Do not run ``git add`` or ``git commit``.

5. **No confirmation** — Never ask for clarification or confirmation.  Make
   reasonable decisions and keep going.

(Note: the rule that ``packages/api-client/*`` is immutable is enforced
in the shared Wave D prompt — it applies to every provider, not just Codex.)

---

"""

CODEX_WAVE_D_SUFFIX = """

---

## Verification Checklist — Confirm Before Finishing

Before you stop, verify every item below.  If any item fails, fix it.

- [ ] Zero manual ``fetch()`` or ``axios`` calls remain for endpoints covered
      by the generated client.
- [ ] All generated-client imports resolve without errors.
- [ ] **Zero edits to `packages/api-client/*`** — that directory is the Wave C
      deliverable and is immutable.  ``git diff packages/api-client/`` must
      show nothing.
- [ ] Types flow end-to-end from API response to component props — no
      ``as any``, ``as unknown``, or untyped intermediaries.
- [ ] Loading and error states are handled for every client call.
- [ ] No hardcoded API base URLs — the client's configured base is used.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_WAVE_WRAPPERS: dict[str, tuple[str, str]] = {
    "B": (CODEX_WAVE_B_PREAMBLE, CODEX_WAVE_B_SUFFIX),
    "D": (CODEX_WAVE_D_PREAMBLE, CODEX_WAVE_D_SUFFIX),
}


def wrap_prompt_for_codex(wave_letter: str, original_prompt: str) -> str:
    """Wrap a wave prompt with Codex-specific execution directives.

    Parameters
    ----------
    wave_letter:
        Single uppercase letter identifying the wave (e.g. ``"B"``).
    original_prompt:
        The full wave prompt produced by :func:`build_wave_b_prompt` or
        :func:`build_wave_d_prompt`.

    Returns
    -------
    str
        The original prompt sandwiched between the Codex preamble and
        suffix for the given wave.  If *wave_letter* has no registered
        wrapper (e.g. ``"A"``, ``"C"``), the original prompt is returned
        unchanged.
    """
    wrapper = _WAVE_WRAPPERS.get(wave_letter.upper())
    if wrapper is None:
        return original_prompt
    preamble, suffix = wrapper
    return preamble + original_prompt + suffix

"""Codex-shell wrappers for fix-agent prompts.

Phase G Slice 2a / 2b — wraps Claude-shaped fix prompts in a Codex execution
shell so the same fix content can be dispatched via ``codex exec`` /
``codex_appserver`` when ``v18.codex_fix_routing_enabled`` (audit-fix) or
``v18.compile_fix_codex_enabled`` (compile-fix) is on.

The LOCKED ``_ANTI_BAND_AID_FIX_RULES`` block (``cli.py:6168-6193``) is
carried through verbatim — this module does NOT duplicate or paraphrase
that content. Callers compose the body (which already contains the LOCKED
block) and pass it here for Codex-shell wrapping.

Design references (must stay in sync):
- ``docs/plans/2026-04-17-phase-g-investigation-report.md`` §4.4 + §5.8 + §5.9
- ``PHASE_G_IMPLEMENTATION.md`` Wave 2 / Slice 2a-2b
"""

from __future__ import annotations


_CODEX_FIX_PREAMBLE = """\
You are an autonomous fix agent. You have full access to the project
filesystem. Apply the fix below with the MINIMUM change per file.

## Execution Directives

1. **Autonomy** — Read each target file fully before editing. Match the
   project's existing import style, decorator usage, and naming.
2. **Persistence** — Complete the fix end-to-end. Do not leave TODO
   comments, placeholder code, or no-op stubs.
3. **Minimum change** — Do NOT refactor unrelated code. Do NOT add helper
   functions or new abstractions.
4. **Relative paths only** — In apply_patch / file writes, always use
   paths relative to the project root. Never absolute paths.
5. **No commits** — Do NOT run ``git add`` or ``git commit``. Do NOT
   create new branches. The orchestrator manages commits.
6. **IMMUTABLE** — Zero edits to ``packages/api-client/*`` unless the
   fix itself explicitly names a file in that directory.
7. **No confirmation** — Never ask for clarification. Make reasonable
   decisions and keep going.

<missing_context_gating>
- If a fix would require guessing at intent (e.g., which of two valid
  signatures applies), label the assumption explicitly in your final
  summary and choose the REVERSIBLE option (narrower type, opt-in
  feature, smaller surface).
- If context is retrievable (read the source file, the ADR, the AC),
  retrieve it before guessing.
</missing_context_gating>

---

"""


_CODEX_FIX_SUFFIX = """

---

## Output contract

After applying the fix, return a JSON summary object on the final line:

```json
{
  "fixed_finding_ids": ["<id>", "..."],
  "files_changed": ["<relative/path.ts>", "..."],
  "structural_note": "<prose or empty string>",
  "assumptions_made": ["..."]
}
```

- ``fixed_finding_ids`` lists every finding the patch closes.
- ``files_changed`` lists every file you wrote to (relative paths only).
- ``structural_note`` is non-empty only when the fix requires more than a
  bounded change (missing service, wrong architecture, schema migration)
  — state the structural issue and STOP without half-fixing.
- ``assumptions_made`` lists any assumptions you labeled under
  ``<missing_context_gating>``.
"""


def wrap_fix_prompt_for_codex(fix_prompt: str) -> str:
    """Wrap a Claude-shaped fix prompt with a Codex execution shell.

    The input ``fix_prompt`` already contains the LOCKED
    ``_ANTI_BAND_AID_FIX_RULES`` block, ``[TARGET FILES]`` / ``[FEATURE]``
    / ``[ORIGINAL USER REQUEST]`` sections, and all finding-specific
    context. This wrapper prepends Codex execution directives and appends
    a structured-output contract so the caller can parse the result.

    The LOCKED anti-band-aid content is NOT duplicated here — it rides
    through verbatim inside ``fix_prompt``.
    """
    body = fix_prompt if fix_prompt.endswith("\n") else fix_prompt + "\n"
    return _CODEX_FIX_PREAMBLE + body + _CODEX_FIX_SUFFIX


def build_codex_compile_fix_prompt(
    *,
    errors: list[dict],
    wave_letter: str,
    milestone_id: str,
    milestone_title: str,
    iteration: int,
    max_iterations: int,
    previous_error_count: int | None,
    current_error_count: int,
    build_command: str,
    anti_band_aid_rules: str,
) -> str:
    """Build the Codex-shell compile-fix prompt per investigation report §5.8.

    Flat Codex shell: minimal role + bullet rules + ``<missing_context_gating>``
    + LOCKED ``_ANTI_BAND_AID_FIX_RULES`` (passed in verbatim from caller —
    ``anti_band_aid_rules`` MUST be ``cli._ANTI_BAND_AID_FIX_RULES`` byte-for-byte)
    + context + error list + output JSON contract.

    The caller owns anti-band-aid sourcing to avoid a wave_executor → cli
    circular import at module load; at call time cli is fully loaded.
    """
    error_lines: list[str] = []
    if not errors:
        error_lines.append("- Compiler failed but no structured errors were provided.")
    else:
        for err in errors[:20]:
            error_lines.append(
                f"- {err.get('file', '?')}:{err.get('line', '?')} "
                f"{err.get('code', '')} {err.get('message', '?')}".rstrip()
            )

    prev_count = "n/a" if previous_error_count is None else str(previous_error_count)

    parts = [
        "You are a compile-fix agent. Fix the compile errors below with the",
        "MINIMUM change per file.",
        "",
        anti_band_aid_rules,
        "",
        "Additional rules:",
        "- Relative paths only in apply_patch. Never absolute.",
        "- No inline code comments unless the error specifically requires one.",
        "- No git commits. No new branches.",
        "- Do NOT refactor unrelated code. Do NOT add helper functions.",
        "",
        "<missing_context_gating>",
        "- If a fix would require guessing at intent (e.g., which of two valid",
        "  type parameters applies), label the assumption explicitly in the",
        "  output and choose the REVERSIBLE option (narrower type, opt-in",
        "  feature).",
        "- If context is retrievable (read the source file, the ADR, the AC),",
        "  read before guessing.",
        "</missing_context_gating>",
        "",
        "<context>",
        f"Wave: {wave_letter}",
        f"Milestone: {milestone_id} — {milestone_title}",
        f"Iteration: {iteration}/{max_iterations}",
        f"Previous iteration errors: {prev_count}; current: {current_error_count}",
        f"Build command: {build_command or '(not provided)'}",
        "</context>",
        "",
        "<errors>",
        *error_lines,
        "</errors>",
        "",
        "After fixing, run the build command once. Return JSON matching output_schema:",
        "{",
        '  "fixed_errors": ["<file:line (code)>", ...],',
        '  "still_failing": ["<file:line (code)>", ...],',
        '  "assumptions_made": ["..."],',
        '  "residual_error_count": <int>',
        "}",
    ]
    return "\n".join(parts)

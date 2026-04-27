"""Phase 4.7a — wave_boundary blocks + allowed-globs narrowing.

Wave B and Wave D prompts gain an explicit ``<wave_boundary>`` XML block
listing the OTHER wave's responsibilities. The 2026-04-26 M1 hardening
smoke's 52KB Wave B prompt had **0 mentions of "Wave D"**: Codex had no
way to know which side of the line frontend chassis fell on. Phase 4.7a
closes that ambiguity by:

1. Injecting a self-identifying boundary block at the top of each wave
   prompt body that names both the current wave's scope and the sibling
   wave's domain (so every Wave B retry reads "Wave D handles
   apps/web/src/i18n/, apps/web/src/middleware.ts, locales/...").
2. Narrowing ``MilestoneScope.allowed_file_globs`` at render time so the
   "Allowed file globs" preamble lists only the current wave's files
   plus wave-agnostic infra. Frontend chassis globs (``apps/web/**``,
   ``locales/**``, ``packages/api-client/**``) drop off Wave B's prompt
   when Wave D is part of the milestone wave-set; symmetric for Wave D.

Closes Risk #22 (wave prompt scope ambiguity).

Master kill switch:
``AuditTeamConfig.wave_boundary_block_enabled`` — default ``True``. Flip
to ``False`` to suppress both the boundary block and the glob narrowing
(rollback path). Production callers may also pass
``wave_boundary_narrow_globs=False`` to ``apply_scope_to_prompt`` for
narrowing-only rollback while keeping the boundary block in the prompt.

Provider compatibility (Context7-verified 2026-04-27):
* ``/anthropics/claude-code`` documents user-emitted XML tags as the
  recommended pattern for structured prompt additions; ``<wave_boundary>``
  is exactly that shape.
* ``/openai/codex`` does not auto-strip XML tags in user prompts (its
  apply_patch grammar uses a non-XML ``*** Begin Patch`` marker that does
  not collide with the boundary block). Codex documentation confirms no
  "I shouldn't touch this file" semantic markers are baked-in (no
  ``// @copilot-ignore`` style support); the boundary block is the
  canonical path for both providers.

Related upstream: Phase 4.3's ``wave_ownership.WAVE_PATH_OWNERSHIP``
maps physical FILE paths to wave letters (used for audit-finding
classification). This module's ``_GLOB_WAVE_OWNERSHIP`` maps GLOB
strings (which may contain ``**`` wildcards) to wave letters and is
deliberately MORE permissive than the path table — globs like
``locales/**`` are not in the path table because no real file lives at
the project root, but the planner-emitted glob explicitly names a
Wave-D-owned domain.
"""

from __future__ import annotations

from typing import Iterable

# ---------------------------------------------------------------------------
# Boundary block templates
# ---------------------------------------------------------------------------

# The boundary block is rendered as XML so both providers (Codex via
# OpenAI Responses API, Claude Code via Anthropic Messages API) recognise
# the structural shape. Verified per Context7 lookups 2026-04-27.

_WAVE_B_BOUNDARY = (
    "<wave_boundary>\n"
    "You are Wave B (BACKEND). Your scope:\n"
    "- apps/api/** (NestJS backend source: modules, services, DTOs)\n"
    "- prisma/** (schema.prisma + migrations + generated client setup)\n"
    "- packages/shared/** (cross-cutting types/utilities, when present)\n"
    "- docker-compose.yml (backend service additions only)\n"
    "- root package.json (workspace declarations only)\n"
    "- apps/web/Dockerfile (frontend image build — backend-managed infra)\n"
    "- apps/web/.env.example (cross-cutting environment template)\n"
    "\n"
    "The following are NOT yours — Wave D (FRONTEND) will create them:\n"
    "- apps/web/src/i18n/** (next-intl request configuration + helpers)\n"
    "- apps/web/locales/** (translation JSON: en, ar, etc.)\n"
    "- apps/web/src/app/** (Next.js App Router routes; layout.tsx is a\n"
    "  SCAFFOLD STUB Wave D finalizes with chrome + locale providers)\n"
    "- apps/web/src/components/** (presentation layer)\n"
    "- apps/web/src/middleware.ts (next-intl + JWT cookie middleware;\n"
    "  SCAFFOLD STUB Wave D finalizes with route matcher + cookie pass-through)\n"
    "- next-intl wiring (request handler, middleware, navigation helpers)\n"
    "- RTL direction switcher (locale-aware <html dir> attribute)\n"
    "- Locale files (en/ar common.json and any other translation bundles)\n"
    "- packages/api-client/** (Wave C produces the generated API client;\n"
    "  IMMUTABLE for Wave B — never edit, regen, or delete)\n"
    "\n"
    "If your work appears to require touching a Wave D file, return\n"
    "`BLOCKED: <reason>` instead of editing it. Wave D will pick up\n"
    "the file after Wave B completes; do not pre-empt the boundary.\n"
    "If a scaffold file under apps/web/ contains a header line of\n"
    "the form `// @scaffold-stub: finalized-by-wave-D`, that file is\n"
    "Wave D's finalize-target — do not modify it.\n"
    "</wave_boundary>"
)

_WAVE_D_BOUNDARY = (
    "<wave_boundary>\n"
    "You are Wave D (FRONTEND). Your scope:\n"
    "- apps/web/src/** (Next.js App Router routes, components, hooks)\n"
    "- apps/web/locales/** (translation files: en, ar, etc.)\n"
    "- apps/web/public/** (static assets: images, fonts, icons)\n"
    "- apps/web/package.json (frontend dependencies only)\n"
    "- apps/web/next.config.* (frontend build config)\n"
    "- apps/web/tailwind.config.* (styling config)\n"
    "- apps/web/postcss.config.* (PostCSS pipeline)\n"
    "\n"
    "The following are NOT yours — other waves own them:\n"
    "- apps/api/** (NestJS BACKEND; Wave B)\n"
    "- prisma/** (database schema + migrations; Wave B)\n"
    "- packages/api-client/** (generated API client; Wave C —\n"
    "  IMMUTABLE for Wave D — import from it; never edit, regen, or delete)\n"
    "- docker-compose.yml top-level structure (Wave B owns infra)\n"
    "- apps/web/Dockerfile (frontend image build; Wave B-managed infra)\n"
    "- apps/web/.env.example (cross-cutting env template; Wave B)\n"
    "- root package.json workspace declarations (Wave B)\n"
    "\n"
    "If your work appears to require touching a backend file, return\n"
    "`BLOCKED: <reason>` instead of editing it. Wave B has already\n"
    "completed by the time Wave D runs; the backend boundary is firm.\n"
    "Use the generated `packages/api-client/` for every backend call.\n"
    "</wave_boundary>"
)


WAVE_BOUNDARY_BLOCKS: dict[str, str] = {
    "B": _WAVE_B_BOUNDARY,
    "D": _WAVE_D_BOUNDARY,
}


def format_wave_boundary_block(wave_letter: str) -> str:
    """Return the ``<wave_boundary>`` block for *wave_letter* (B or D).

    Returns the empty string for waves that don't have a boundary block
    today (A, A5, C, T, T5, E, D5). Those waves lack a sibling-wave
    ambiguity that the boundary block exists to clarify:

    * Wave A is the sole architect — there's no sibling architect.
    * Wave C produces ``packages/api-client/`` only; the path is
      unambiguous and Wave C never executes alongside another wave.
    * Wave T runs full e2e after every implementation wave; its scope
      is ``e2e/tests/<milestone>/`` only.
    * Wave E adds Playwright skeleton files under ``e2e/`` only.
    * Wave D5 (legacy polish-only path) operates on Wave D's outputs.
    """
    return WAVE_BOUNDARY_BLOCKS.get((wave_letter or "").upper(), "")


# ---------------------------------------------------------------------------
# Allowed-globs narrowing
# ---------------------------------------------------------------------------

# Map planner-emitted globs to their owner wave letter. This is a
# DIFFERENT (more permissive) table than Phase 4.3's
# ``wave_ownership.WAVE_PATH_OWNERSHIP`` because it operates on glob
# STRINGS, not concrete file paths. The planner emits globs like
# ``locales/**`` that don't appear in the path table (the path table
# only knows ``apps/web/locales/...``); for prompt-scope purposes we
# trust the glob's intent.
#
# Entry order is preserved at iteration; specific-prefix entries should
# come before broader ones if they ever conflict (today no entry is a
# prefix of another).
_GLOB_WAVE_OWNERSHIP: dict[str, str] = {
    # Wave B — backend infra
    "apps/api/**": "B",
    "apps/api/*": "B",
    "prisma/**": "B",
    "prisma/*": "B",
    "packages/shared/**": "B",
    # Wave C — generated API client
    "packages/api-client/**": "C",
    "packages/api-client/*": "C",
    # Wave D — frontend infra
    "apps/web/**": "D",
    "apps/web/*": "D",
    "apps/web/src/**": "D",
    "apps/web/src/i18n/**": "D",
    "apps/web/src/components/**": "D",
    "apps/web/src/app/**": "D",
    "apps/web/src/middleware.ts": "D",
    "apps/web/locales/**": "D",
    "apps/web/public/**": "D",
    "apps/web/next.config.*": "D",
    "apps/web/tailwind.config.*": "D",
    "apps/web/postcss.config.*": "D",
    "locales/**": "D",
    "locales/*": "D",
    # Wave T — end-to-end test surface
    "e2e/**": "T",
    "e2e/*": "T",
    "e2e/tests/**": "T",
    "tests/**": "T",
    "tests/*": "T",
}

# Specific cross-wave keepers: globs/paths that look like they belong
# to a sibling wave but are managed by the named wave for infra reasons.
# Wave B owns the apps/web/ image build + cross-cutting env template,
# even though apps/web/ source belongs to Wave D.
_INFRA_EXCEPTIONS: dict[str, str] = {
    "apps/web/Dockerfile": "B",
    "apps/web/.env.example": "B",
    # Truly wave-agnostic: every wave can touch them when justified.
    "docker-compose.yml": "wave-agnostic",
    ".env.example": "wave-agnostic",
    "package.json": "wave-agnostic",
    "pnpm-lock.yaml": "wave-agnostic",
    "pnpm-workspace.yaml": "wave-agnostic",
    "tsconfig.base.json": "wave-agnostic",
    ".gitignore": "wave-agnostic",
}


# Phase 4.7a only narrows for the two ambiguity-prone waves. Other
# waves preserve their pre-Phase-4.7 verbatim glob lists.
_NARROWED_WAVES: frozenset[str] = frozenset({"B", "D"})


def _glob_owner_wave(glob: str) -> str:
    """Map a glob string to its owner wave letter (or ``wave-agnostic``).

    Looks up *glob* directly in ``_GLOB_WAVE_OWNERSHIP``; if no exact
    match, defers to Phase 4.3's ``wave_ownership.resolve_owner_wave``
    against the glob's representative path prefix (the prefix before the
    first wildcard character). The Phase 4.3 path table covers the
    common ``apps/api/...``, ``apps/web/...``, ``packages/api-client/...``
    cases that may show up as fully-qualified file paths in the
    allowed-glob list.
    """
    if not glob:
        return "wave-agnostic"
    direct = _GLOB_WAVE_OWNERSHIP.get(glob)
    if direct:
        return direct
    # Strip wildcards to derive a representative path prefix, then defer
    # to Phase 4.3's path-based classifier (imported lazily to avoid a
    # module-load-time cycle).
    representative = glob.split("*", 1)[0].rstrip("/")
    if not representative:
        return "wave-agnostic"
    try:
        from .wave_ownership import resolve_owner_wave
    except Exception:
        return "wave-agnostic"
    return resolve_owner_wave(representative)


def narrow_allowed_globs_for_wave(
    globs: Iterable[str],
    wave_letter: str,
) -> list[str]:
    """Filter *globs* down to the set the named wave should see.

    A glob is dropped when its owner resolves to a DIFFERENT, known
    wave letter (B/C/D/T) and that wave is one of the implementation
    waves the milestone may run. Wave-agnostic globs and globs owned by
    the current wave survive. Specific infra exceptions (e.g.,
    ``apps/web/Dockerfile`` for Wave B) are preserved by exact-match
    lookup before the ownership filter applies.

    For waves not in ``_NARROWED_WAVES`` (today: B and D), the input
    list is returned unchanged — Phase 4.7a's narrowing is intentionally
    scoped to the two ambiguity-prone waves.
    """
    glob_list = [g for g in globs if g]
    wave = (wave_letter or "").upper()
    if wave not in _NARROWED_WAVES:
        return list(glob_list)

    out: list[str] = []
    for g in glob_list:
        gnorm = g.strip()
        if not gnorm:
            continue

        # Specific cross-wave keepers (e.g., apps/web/Dockerfile for B):
        # if the exception names this wave OR is wave-agnostic, keep it.
        # If the exception names a different wave, drop it.
        exception = _INFRA_EXCEPTIONS.get(gnorm)
        if exception is not None:
            if exception == wave or exception == "wave-agnostic":
                out.append(g)
            # else: exception names a sibling wave — drop.
            continue

        owner = _glob_owner_wave(gnorm)
        if owner == wave:
            out.append(g)
            continue
        if owner == "wave-agnostic":
            out.append(g)
            continue
        if owner in {"B", "C", "D", "T"}:
            # Owner is a known implementation wave that is NOT us —
            # this glob belongs to a sibling wave, drop it.
            continue
        # Owner unrecognised (shouldn't happen with the current table,
        # but stay defensive): keep the glob so we don't silently
        # delete planner intent.
        out.append(g)
    return out


__all__ = [
    "WAVE_BOUNDARY_BLOCKS",
    "format_wave_boundary_block",
    "narrow_allowed_globs_for_wave",
]

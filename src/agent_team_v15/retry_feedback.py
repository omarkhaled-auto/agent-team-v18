"""Phase 4.2 — strong deterministic retry feedback.

Replaces the legacy ~150-byte ``<previous_attempt_failed>`` block with a
structured, deterministic, LLM-cost-zero payload composed from already-
captured signal: BuildKit inner stderr (wrapper stripped), parsed
TypeScript / Next.js compile errors with file:line, unresolved-import
scan from modified files, and a progressive signal across retries.

Plan: ``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §E
(Section E — Phase 4.2 Detail).

Risk #29 mitigation
-------------------
Codex sandboxes cannot run ``docker compose build`` in their isolated
environment (Windows buildx lock conflict — known limitation per §M.3).
The richer feedback REMOVES the need for Codex to reproduce the failure
locally: parsed errors with file:line + unresolved-import findings give
Codex enough to make targeted edits without re-running the failing
command. The payload includes an explicit "DO NOT re-run docker compose
build" directive so Codex isn't tempted to attempt reproduction.

WAVE_FINDINGS attribution, NOT protocol-log narration
-----------------------------------------------------
``compute_progressive_signal`` sources ``failing_services`` from
WAVE_FINDINGS-shaped per-attempt outcome data — what HAPPENED on each
attempt — NOT from the prior protocol log's ``<previous_attempt_failed>``
block content (what Codex was TOLD on that turn). The 2026-04-26 smoke
exposed the discrepancy: protocol log retry=2's block reported
``service=api`` (echoing retry=1's failure), while WAVE_FINDINGS.json
retry=2 entry showed retry=2 actually failed on ``service=web``.
``compute_progressive_signal`` uses the per-attempt ``failing_services``
list in ``prior_attempts``, which the wave_executor populates from
``self_verify_findings`` (WAVE_FINDINGS-shaped data) — never from the
prior turn's narration.

Bounded-size contract
---------------------
``build_retry_payload`` returns a UTF-8 byte-bounded string at
``max_size_bytes`` (default 12000). Pathological inputs trigger
progressive truncation that preserves the opening / closing tags so the
consumer parser can always locate the boundaries. The ≥10× richness
target (≥1500 bytes vs ~150-byte legacy baseline per plan §0.3 step 2)
is enforced by the test suite, not by a runtime floor — the module
fills the available budget with structured signal when inputs are
non-empty.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Regex shapes — Context7-locked against current minor versions
# ---------------------------------------------------------------------------

# TypeScript ``tsc --noEmit --pretty=false`` canonical diagnostic:
#   ``path/to/file.ts(line,col): error TSXXXX: message``
# Source: ``/microsoft/typescript`` baseline reference output (e.g.
# ``parserRegularExpressionDivideAmbiguity4.ts(1,1): error TS2304: ...``).
# Locked 2026-04-27.
_TSC_ERROR_RE = re.compile(
    r"^(?P<file>[^\(\n]+?)\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+"
    r"(?P<code>TS\d+):\s*(?P<message>.+?)$",
    re.MULTILINE,
)

# BuildKit ``failed to solve: process X did not complete successfully``
# wrapper. The pre-wrapper bytes are the actual command stderr; the
# wrapper itself just announces the exit code. Optionally prefixed with
# ``target <service>:`` (compose-driven build).
# Source: ``/moby/buildkit`` + 2026-04-26 smoke evidence (frozen at
# ``tests/fixtures/smoke_2026_04_26/codex-captures/``).
_BUILDKIT_WRAPPER_RE = re.compile(
    r"(?:^|\n)(?:>?\s*\[.*?\]\s*)?"
    r"(?:target\s+(?P<service>\S+):\s+)?"
    r"failed to solve:\s*"
    r"process\s+\"(?P<command>[^\"]+)\"\s+"
    r"did not complete successfully:\s*exit code:\s*(?P<exit_code>\d+)",
    re.MULTILINE,
)

# Next.js ``next build`` error blocks. Two canonical shapes:
#   ``./path:line:col`` (compile error location line)
#   ``Module not found: Can't resolve '<target>'`` (resolver failure)
# Source: ``/vercel/next.js`` — the ``turbopackIgnoreIssue`` doc confirms
# ``Module not found`` is the canonical issue title; the
# ``browserToTerminal`` doc confirms ``./file:line:col`` is the location
# format. Locked 2026-04-27.
_NEXTJS_FILE_RE = re.compile(
    r"^\.\/(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+)\s*$",
    re.MULTILINE,
)
_NEXTJS_MODULE_NOT_FOUND_RE = re.compile(
    r"Module not found:\s*(?:Can'?t resolve|Error:[^\n']*)\s*'(?P<target>[^']+)'",
)
_NEXTJS_TYPE_ERROR_RE = re.compile(
    r"Type error:\s*(?P<message>.+?)$",
    re.MULTILINE,
)

# TypeScript / JavaScript import/require shapes for unresolved-import
# scanning. Reuses the path-shaped contract pattern from
# ``fix_executor.py`` (Phase 3.5) but tightened to import-statement
# context.
_TS_IMPORT_RE = re.compile(
    r"""(?x)
    ^\s*
    (?:import|export)\s+
    (?:[^'"]*?\s+from\s+)?
    ['"](?P<target>[^'"\n]+)['"]
    """,
    re.MULTILINE,
)
_TS_REQUIRE_RE = re.compile(
    r"""(?x)
    require\(
    \s*['"](?P<target>[^'"\n]+)['"]\s*
    \)
    """,
)


# ---------------------------------------------------------------------------
# Structured-error extractors
# ---------------------------------------------------------------------------


def extract_typescript_errors(stderr: str) -> list[dict[str, Any]]:
    """Parse ``tsc --noEmit --pretty=false`` output into structured errors.

    Each result: ``{"file": str, "line": int, "col": int, "code": str,
    "message": str}``. Returns ``[]`` on no match — never raises.
    """
    out: list[dict[str, Any]] = []
    if not stderr:
        return out
    for m in _TSC_ERROR_RE.finditer(stderr):
        out.append({
            "file": m.group("file").strip(),
            "line": int(m.group("line")),
            "col": int(m.group("col")),
            "code": m.group("code"),
            "message": m.group("message").strip(),
        })
    return out


def extract_buildkit_inner_stderr(stderr: str) -> str:
    """Strip the ``failed to solve: process X did not complete`` wrapper
    to expose the inner command's actual stderr.

    The pre-wrapper text is the inner command output (TypeScript errors,
    pnpm errors, etc.). When no wrapper is present, returns the input
    unchanged. When the wrapper is present but no preceding output
    exists, returns the full input (defensive — better to over-include
    than drop signal).
    """
    if not stderr:
        return ""
    match = _BUILDKIT_WRAPPER_RE.search(stderr)
    if match is None:
        return stderr.strip()
    inner = stderr[: match.start()].rstrip()
    return inner if inner else stderr.strip()


def extract_nextjs_build_errors(stderr: str) -> list[dict[str, Any]]:
    """Parse ``next build`` stderr for compile errors, type errors, and
    Module not found resolutions.

    Each result has a ``"kind"`` discriminator: ``"compile_error"`` (with
    ``file/line/col``), ``"module_not_found"`` (with ``target``), or
    ``"type_error"`` (with ``message``).
    """
    out: list[dict[str, Any]] = []
    if not stderr:
        return out
    for m in _NEXTJS_FILE_RE.finditer(stderr):
        out.append({
            "kind": "compile_error",
            "file": m.group("file").strip(),
            "line": int(m.group("line")),
            "col": int(m.group("col")),
        })
    for m in _NEXTJS_MODULE_NOT_FOUND_RE.finditer(stderr):
        out.append({
            "kind": "module_not_found",
            "target": m.group("target"),
        })
    for m in _NEXTJS_TYPE_ERROR_RE.finditer(stderr):
        out.append({
            "kind": "type_error",
            "message": m.group("message").strip(),
        })
    return out


def scan_unresolved_imports(
    modified_files: list[str],
    project_root: str,
) -> list[dict[str, Any]]:
    """Walk modified TS/JS files; for each ``import ... from '...'`` or
    ``require('...')``, check the target exists on disk.

    Returns ``[{"file": str, "line": int, "import_target": str,
    "kind": "missing"}]`` for imports whose target cannot be resolved
    via standard TS/JS resolution rules:
    - Bare specifiers (no leading ``.`` or ``/``) are SKIPPED — those
      resolve via node_modules and we can't confirm without parsing
      ``package.json`` deeply.
    - Relative targets are checked against ``<dir>/<target>``,
      ``<dir>/<target>.{ts,tsx,js,jsx}``, and
      ``<dir>/<target>/index.{ts,tsx,js,jsx}`` (TS resolution semantics).

    Non-TS/JS files in ``modified_files`` are skipped silently. Missing
    files (deleted between the wave and this scan) are skipped silently.
    """
    out: list[dict[str, Any]] = []
    if not modified_files or not project_root:
        return out
    root = Path(project_root)
    for rel in modified_files:
        rel_str = str(rel)
        if not rel_str.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
            continue
        abs_path = root / rel_str
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_num, line in enumerate(content.splitlines(), start=1):
            target: str | None = None
            for pattern, mode in (
                (_TS_IMPORT_RE, "match"),
                (_TS_REQUIRE_RE, "search"),
            ):
                m = (
                    pattern.match(line)
                    if mode == "match"
                    else pattern.search(line)
                )
                if m:
                    target = m.group("target")
                    break
            if not target:
                continue
            # Skip bare specifiers (node_modules-resolved).
            if not (target.startswith(".") or target.startswith("/")):
                continue
            # Resolve the target against the importer's directory.
            try:
                base = abs_path.parent / target
                base_resolved = base.resolve()
            except (OSError, ValueError):
                continue
            candidates = [
                base_resolved,
                base_resolved.with_suffix(".ts"),
                base_resolved.with_suffix(".tsx"),
                base_resolved.with_suffix(".js"),
                base_resolved.with_suffix(".jsx"),
                base_resolved.with_suffix(".mjs"),
                base_resolved.with_suffix(".cjs"),
                base_resolved / "index.ts",
                base_resolved / "index.tsx",
                base_resolved / "index.js",
                base_resolved / "index.jsx",
            ]
            if any(c.exists() for c in candidates):
                continue
            out.append({
                "file": rel_str,
                "line": line_num,
                "import_target": target,
                "kind": "missing",
            })
    return out


# ---------------------------------------------------------------------------
# Progressive signal — sources from WAVE_FINDINGS-shaped attribution
# ---------------------------------------------------------------------------


def compute_progressive_signal(
    this_attempt: dict[str, Any],
    prior_attempts: list[dict[str, Any]],
) -> str:
    """Produce the cross-retry progress narrative.

    Compares ``this_attempt['failing_services']`` (current attempt's
    actual failure set, sourced from ``BuildResult.service`` per-wave)
    against ``prior_attempts[-1]['failing_services']`` (the most recent
    prior attempt's WAVE_FINDINGS-shaped failure set).

    Returns ``""`` when there are no prior attempts (regression-safe
    contract: retry=0 has no progressive signal).

    Plan §E AC4 + the user-flagged WAVE_FINDINGS-not-protocol-log
    invariant: the comparison data MUST be the per-attempt outcome
    (what HAPPENED), not parsed text from the prior turn's
    ``<previous_attempt_failed>`` block (what Codex was TOLD).
    """
    if not prior_attempts:
        return ""
    last_prior = prior_attempts[-1]
    prior_services = set(last_prior.get("failing_services") or [])
    this_services = set(this_attempt.get("failing_services") or [])
    if not prior_services and not this_services:
        return ""

    fixed = sorted(prior_services - this_services)
    new_only = sorted(this_services - prior_services)
    overlapping = sorted(prior_services & this_services)

    parts: list[str] = []
    parts.append(
        f"Previous retry (#{last_prior.get('retry', '?')}): "
        f"{', '.join(sorted(prior_services)) or 'no failures recorded'} FAILED."
    )
    parts.append(
        f"This retry (#{this_attempt.get('retry', '?')}): "
        f"{', '.join(sorted(this_services)) or 'no failures'} FAILED."
    )
    if fixed and not overlapping:
        parts.append(
            f"Fixed since last attempt: {', '.join(fixed)} "
            f"now PASSED — keep these changes."
        )
    elif fixed:
        parts.append(
            f"Fixed since last attempt: {', '.join(fixed)} "
            f"PASSED — keep these changes."
        )
    if new_only:
        parts.append(
            f"NEW failures unmasked this retry: {', '.join(new_only)}."
        )
    if overlapping and not fixed and not new_only:
        parts.append(
            f"No progress: {', '.join(overlapping)} still FAILED."
        )
    if this_services:
        parts.append(f"Focus next: {', '.join(sorted(this_services))}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Legacy ~150-byte payload — preserved as rollback contract
# ---------------------------------------------------------------------------


_LEGACY_REQUIREMENTS_BY_WAVE: dict[str, list[str]] = {
    "B": [
        "Every Dockerfile COPY/ADD source must resolve inside build.context.",
        "`docker compose build` must succeed for all services.",
        "Use `apply_patch` to edit files, never shell redirection.",
    ],
    "D": [
        "Every Dockerfile COPY/ADD source must resolve inside build.context.",
        "`docker compose build web` must succeed.",
        "Use `apply_patch` to edit files, never shell redirection.",
    ],
}


# Wave-scope teaching content — deterministic per wave_letter, derived from
# the canonical wave responsibilities documented in
# docs/plans/2026-04-26-pipeline-upgrade-phase4.md §J.4.7a (the future
# <wave_boundary> block) + the smoke evidence at
# tests/fixtures/smoke_2026_04_26/. Bundled into build_retry_payload so the
# payload reaches the ≥1500-byte richness floor even for sparse inputs
# (e.g., when the just-failed attempt's stderr is a thin BuildKit wrapper
# without inner TS errors — exactly the 2026-04-26 smoke shape).
_WAVE_SCOPE_TEACHING: dict[str, str] = {
    "B": (
        "Wave B is the BACKEND wave. Your deliverable is the `apps/api/` "
        "service: NestJS modules, Prisma schema, the `apps/api/Dockerfile`, "
        "the `api` service block in `docker-compose.yml`, and any backend "
        "package files (`apps/api/package.json`, `tsconfig.json`). The "
        "`docker compose build api` command MUST succeed against your "
        "output.\n\n"
        "Files OUT OF SCOPE for Wave B (Wave D / Wave C own these — do "
        "not modify):\n"
        "- `apps/web/**` (Next.js frontend chassis — Wave D)\n"
        "- `packages/api-client/**` (shared client; Wave C generates)\n"
        "- `apps/web/locales/**`, `apps/web/src/i18n/**`, "
        "`apps/web/src/middleware.ts` (Wave D's frontend stubs)\n"
        "- E2E tests under `e2e/` or root `tests/` (Wave T)"
    ),
    "D": (
        "Wave D is the FRONTEND chassis wave. Your deliverable is the "
        "`apps/web/` Next.js app: i18n wiring (next-intl), locale files "
        "under `apps/web/locales/`, layout components, the "
        "`apps/web/Dockerfile`, the `web` service block in "
        "`docker-compose.yml`, and the middleware. The "
        "`docker compose build web` command MUST succeed against your "
        "output.\n\n"
        "Files OUT OF SCOPE for Wave D (Wave B / Wave C / Wave T own "
        "these — do not modify):\n"
        "- `apps/api/**` (NestJS backend — Wave B)\n"
        "- `prisma/**` (database schema — Wave B)\n"
        "- `packages/api-client/**` (Wave C's generated client)\n"
        "- E2E tests under `e2e/` or root `tests/` (Wave T)"
    ),
}


# Common-failure-pattern checklist — one entry per wave_letter. Drawn from
# the 2026-04-26 smoke post-mortem (smoke_2026-04-26_landing.md "Failure
# mode classification") and Phase 1-3 audit-fix-loop guardrails findings.
# Static (deterministic) content — adds actionable steering without an
# LLM call. Extended payload helps Codex avoid the same root causes
# observed in real runs.
_COMMON_FAILURES_CHECKLIST: dict[str, list[str]] = {
    "B": [
        (
            "**Prisma in `dependencies`**: `pnpm --filter api build` runs "
            "`prisma generate` during prebuild. If Prisma is in "
            "`dependencies` and the production install has only "
            "production deps, generate fails. Move `prisma` to "
            "`devDependencies`; keep `@prisma/client` in `dependencies`."
        ),
        (
            "**Dockerfile COPY/ADD outside build.context**: every COPY "
            "src must resolve INSIDE the directory `build.context` "
            "points to. For workspace packages, set `build.context: .` "
            "(repo root) and COPY the specific subtree, not "
            "`build.context: apps/api/` then COPY `../packages/...`."
        ),
        (
            "**Missing module imports (NestJS)**: a controller using "
            "`JwtAuthGuard` requires the parent module to import "
            "`AuthModule` — otherwise `JwtAuthGuard` resolves to "
            "undefined at bootstrap and `tsc` won't catch it."
        ),
        (
            "**Type-only imports leaking into runtime**: `import type` "
            "statements are erased at compile time. If you `import` a "
            "value but only use its type, fix to `import type`. "
            "Inverse mistake (importing a type as a value) breaks "
            "runtime."
        ),
        (
            "**Shadow `.d.ts` files**: a hand-written `foo.d.ts` next "
            "to a generated `foo.js` will shadow the real types. "
            "Delete the hand-written shadow."
        ),
    ],
    "D": [
        (
            "**Missing locale files**: next-intl wiring expects "
            "`apps/web/locales/<lang>/<ns>.json` to exist for every "
            "configured locale. Empty / absent locale files cause a "
            "runtime crash at first render."
        ),
        (
            "**Hardcoded `lang='en'` in root layout**: the root "
            "`apps/web/src/app/layout.tsx` must read locale from the "
            "request (next-intl middleware) — hardcoding `lang='en'` "
            "breaks RTL/Arabic switching."
        ),
        (
            "**Missing middleware stub finalization**: "
            "`apps/web/src/middleware.ts` may exist as a scaffold no-op. "
            "Wave D must finalize it with locale detection + JWT cookie "
            "forwarding (the smoke's F-001 critical finding)."
        ),
        (
            "**Type-only imports leaking into runtime**: `import type` "
            "statements are erased at compile time. If you `import` a "
            "value but only use its type, fix to `import type`."
        ),
        (
            "**Dockerfile COPY/ADD outside build.context**: every COPY "
            "src must resolve INSIDE the directory `build.context` "
            "points to. For workspace packages, set `build.context: .` "
            "(repo root)."
        ),
    ],
}


def _legacy_retry_prompt_suffix(
    error_summary: str,
    *,
    wave_letter: str = "B",
) -> str:
    """Pre-Phase-4.2 ``<previous_attempt_failed>`` block — preserved as
    the rollback path when ``AuditTeamConfig.strong_retry_feedback_enabled``
    is False. One release cycle of legacy fallback per plan §0.3 step
    2.2.
    """
    requirements = _LEGACY_REQUIREMENTS_BY_WAVE.get(
        wave_letter, _LEGACY_REQUIREMENTS_BY_WAVE["B"]
    )
    req_lines = "\n".join(f"- {r}" for r in requirements)
    return (
        "<previous_attempt_failed>\n"
        f"Your previous Wave {wave_letter} output failed acceptance testing. "
        "You MUST fix these issues in this retry. Do NOT repeat the same mistakes.\n\n"
        f"{error_summary}\n\n"
        "Requirements for this retry:\n"
        f"{req_lines}\n"
        "</previous_attempt_failed>"
    )


# ---------------------------------------------------------------------------
# Helpers for build_retry_payload
# ---------------------------------------------------------------------------


def _derive_failing_services_from_stderr(stderr: str) -> list[str]:
    """Best-effort: pull ``service=<name>`` and BuildKit ``target <name>:``
    markers from the just-failed attempt's stderr."""
    services: list[str] = []
    seen: set[str] = set()
    if not stderr:
        return services
    for m in re.finditer(r"service=(\S+)", stderr):
        s = m.group(1).rstrip(":,;)")
        if s and s not in seen:
            seen.add(s)
            services.append(s)
    for m in _BUILDKIT_WRAPPER_RE.finditer(stderr):
        s = (m.group("service") or "").strip()
        if s and s not in seen:
            seen.add(s)
            services.append(s)
    return services


def _truncate_stderr_tail(stderr: str, max_chars: int = 5000) -> str:
    """Return the last ``max_chars`` of stderr, prefixed with a
    machine-readable truncation marker when truncation occurred."""
    if not stderr:
        return ""
    if len(stderr) <= max_chars:
        return stderr
    full_bytes = len(stderr.encode("utf-8"))
    return (
        f"…(truncated; full stderr {full_bytes} bytes)\n"
        + stderr[-max_chars:]
    )


_OPEN_TAG = "<previous_attempt_failed>"
_CLOSE_TAG = "</previous_attempt_failed>"


def _bound_payload_size(payload: str, max_size_bytes: int) -> str:
    """Hard-truncate to ``max_size_bytes`` while preserving the
    open/close tags so the consumer parser can always find boundaries.
    """
    if len(payload.encode("utf-8")) <= max_size_bytes:
        return payload
    closing = "\n…(payload truncated to fit max_size_bytes)\n" + _CLOSE_TAG
    closing_bytes = closing.encode("utf-8")
    budget = max_size_bytes - len(closing_bytes)
    if budget <= 0:
        # Pathological max_size_bytes — return a minimal valid payload.
        return _OPEN_TAG + closing
    encoded = payload.encode("utf-8")
    head = encoded[:budget].decode("utf-8", errors="ignore")
    # If we cut the closing tag mid-bytes, drop any stale partial.
    if _CLOSE_TAG in head:
        head = head[: head.rfind(_CLOSE_TAG)]
    return head + closing


# ---------------------------------------------------------------------------
# Public entry point — build_retry_payload
# ---------------------------------------------------------------------------


def build_retry_payload(
    *,
    stderr: str,
    modified_files: list[str],
    project_root: str,
    prior_attempts: list[dict[str, Any]],
    wave_letter: str,
    max_size_bytes: int = 12000,
    error_summary: str | None = None,
    extra_violations: list[dict[str, Any]] | None = None,
    this_retry_index: int | None = None,
) -> str:
    """Compose the Phase 4.2 ``<previous_attempt_failed>`` block.

    Parameters
    ----------
    stderr:
        Concatenated raw stderr from the just-failed build attempt
        (typically per-service stderrs joined by service-prefixed
        markers). The TypeScript / Next.js / BuildKit extractors run
        against this text plus the wrapper-stripped inner stderr.
    modified_files:
        Files Codex modified during the just-failed wave dispatch
        (sourced from ``wave_result.files_created + files_modified``).
        Used for unresolved-import scanning. Pass ``[]`` when the
        caller doesn't have file-level telemetry available.
    project_root:
        Absolute path to the run-dir / cwd. Used for resolving relative
        import targets against ``modified_files``.
    prior_attempts:
        List of WAVE_FINDINGS-shaped entries for retries BEFORE this
        attempt. Each entry: ``{"retry": int, "failing_services":
        list[str], "error_summary": str (optional)}``. Empty list →
        this is retry=0's failure (the very first attempt).
    wave_letter:
        ``"B"`` or ``"D"`` — controls framing (Wave name, build
        command). Other letters fall back to Wave B framing.
    max_size_bytes:
        Hard ceiling on payload size (UTF-8 bytes). Default 12000 per
        plan §E AC6. Truncation preserves open/close tags.
    error_summary:
        Optional pre-formatted summary (the legacy
        ``_build_error_summary`` output). When provided, included as a
        "Service-level summary" section.
    extra_violations:
        Optional list of compose-sanity violation dicts (each with
        ``service``, ``source``, ``reason``, ``resolved_path``).
    this_retry_index:
        Zero-based index of the just-failed attempt. When omitted,
        derived from ``prior_attempts``.

    Returns
    -------
    str
        The composed ``<previous_attempt_failed>`` block, or ``""``
        when called with degenerate inputs (no failure data, no priors)
        — preserves the regression-safe AC5 contract that retry=0's
        prompt has no retry block.
    """
    has_any_signal = bool(
        stderr
        or error_summary
        or prior_attempts
        or extra_violations
        or modified_files
    )
    if not has_any_signal:
        return ""

    if this_retry_index is None:
        this_retry_index = (
            (prior_attempts[-1].get("retry", -1) + 1)
            if prior_attempts
            else 0
        )

    this_failing = _derive_failing_services_from_stderr(stderr or "")
    this_attempt = {
        "retry": this_retry_index,
        "failing_services": this_failing,
    }

    progressive = compute_progressive_signal(this_attempt, prior_attempts)
    inner_stderr = extract_buildkit_inner_stderr(stderr or "")
    tsc_errors = extract_typescript_errors(stderr or "")
    if not tsc_errors and inner_stderr != (stderr or ""):
        tsc_errors = extract_typescript_errors(inner_stderr)
    nextjs_errors = extract_nextjs_build_errors(stderr or "")
    if not nextjs_errors and inner_stderr != (stderr or ""):
        nextjs_errors = extract_nextjs_build_errors(inner_stderr)
    unresolved = scan_unresolved_imports(
        modified_files or [], project_root or ""
    )

    parts: list[str] = []
    parts.append(_OPEN_TAG)
    parts.append(
        f"Wave {wave_letter} retry={this_retry_index}. Your previous Wave "
        f"{wave_letter} output failed acceptance testing. You MUST fix "
        "these issues; do NOT repeat the same mistakes."
    )

    if progressive:
        parts.append("")
        parts.append("## Progressive signal across retries")
        parts.append(progressive)

    if error_summary:
        parts.append("")
        parts.append("## Service-level summary (this attempt)")
        parts.append(error_summary)

    truncated_inner = _truncate_stderr_tail(inner_stderr, max_chars=5000)
    if truncated_inner.strip():
        parts.append("")
        parts.append("## Build stderr (last 5000 chars of inner command output)")
        parts.append(truncated_inner.rstrip())

    wrapper_match = _BUILDKIT_WRAPPER_RE.search(stderr or "")
    if wrapper_match is not None:
        parts.append("")
        parts.append("## BuildKit wrapper detail")
        parts.append(
            f"- service={wrapper_match.group('service') or '<unknown>'}\n"
            f"- inner command: {wrapper_match.group('command')}\n"
            f"- exit code: {wrapper_match.group('exit_code')}"
        )

    if tsc_errors:
        parts.append("")
        parts.append("## Parsed TypeScript errors (this attempt)")
        for err in tsc_errors[:25]:
            parts.append(
                f"- {err['file']}({err['line']},{err['col']}): "
                f"{err['code']}: {err['message']}"
            )
        if len(tsc_errors) > 25:
            parts.append(f"…(+{len(tsc_errors) - 25} more)")

    if nextjs_errors:
        parts.append("")
        parts.append("## Parsed Next.js build errors (this attempt)")
        for err in nextjs_errors[:25]:
            kind = err.get("kind", "?")
            if kind == "compile_error":
                parts.append(
                    f"- compile error at {err['file']}:{err['line']}:{err['col']}"
                )
            elif kind == "module_not_found":
                parts.append(f"- module_not_found: {err['target']}")
            elif kind == "type_error":
                parts.append(f"- type_error: {err['message'][:200]}")
        if len(nextjs_errors) > 25:
            parts.append(f"…(+{len(nextjs_errors) - 25} more)")

    if unresolved:
        parts.append("")
        parts.append("## Unresolved imports in modified files")
        for u in unresolved[:25]:
            parts.append(
                f"- {u['file']}:{u['line']} → {u['import_target']} "
                f"({u['kind']})"
            )
        if len(unresolved) > 25:
            parts.append(f"…(+{len(unresolved) - 25} more)")

    if modified_files:
        parts.append("")
        parts.append("## Files Codex modified this attempt")
        for f in modified_files[:50]:
            parts.append(f"- {f}")
        if len(modified_files) > 50:
            parts.append(f"…(+{len(modified_files) - 50} more)")

    if extra_violations:
        parts.append("")
        parts.append("## Compose sanity violations")
        for v in extra_violations[:20]:
            parts.append(
                f"- service={v.get('service', '?')} "
                f"source={v.get('source', '?')!r} "
                f"reason={v.get('reason', '?')} "
                f"resolved={v.get('resolved_path', '?')}"
            )

    # Wave-scope teaching — deterministic per wave_letter, adds actionable
    # boundary context. This is what brings sparse-input payloads above
    # the ≥1500-byte richness floor (per plan §0.3 step 2 + §E AC).
    scope_teaching = _WAVE_SCOPE_TEACHING.get(wave_letter)
    if scope_teaching:
        parts.append("")
        parts.append(f"## Wave {wave_letter} scope reminder")
        parts.append(scope_teaching)

    # Common-failure-pattern checklist — also deterministic, drawn from
    # the 2026-04-26 smoke post-mortem. Helps Codex triage the most-
    # observed root causes without re-running the failing command.
    common = _COMMON_FAILURES_CHECKLIST.get(wave_letter)
    if common:
        parts.append("")
        parts.append(
            f"## Common Wave {wave_letter} failure patterns "
            "(use as a triage checklist)"
        )
        for entry in common:
            parts.append(f"- {entry}")

    parts.append("")
    parts.append("## Requirements for this retry")
    parts.append(
        "- Use `apply_patch` to edit files; never shell redirection. "
        "Shell redirection (>, >>) is unreliable in Codex sandboxes and "
        "frequently produces partial files."
    )
    parts.append(
        "- Every Dockerfile COPY/ADD source must resolve inside "
        "`build.context`. If you COPY `../packages/foo`, ensure "
        "`build.context: .` (repo root), not the service subdirectory."
    )
    if wave_letter == "D":
        parts.append(
            "- `docker compose build web` must succeed. The parent "
            "process will re-run this build after your retry; do NOT "
            "reproduce it in your sandbox."
        )
    elif wave_letter == "B":
        parts.append(
            "- `docker compose build api` must succeed. The parent "
            "process will re-run this build after your retry; do NOT "
            "reproduce it in your sandbox."
        )
    else:
        parts.append(
            "- `docker compose build` for your service must succeed."
        )
    parts.append(
        "- DO NOT re-run `docker compose build` in your sandbox — your "
        "sandbox cannot run it (Windows buildx lock conflict; "
        "Risk #29 known limitation per "
        "docs/plans/2026-04-26-pipeline-upgrade-phase4.md §M.3). Use "
        "the parsed errors and unresolved-import findings above to make "
        "targeted edits without reproduction."
    )
    parts.append(
        f"- If a fix requires a file outside Wave {wave_letter}'s scope, "
        "return `BLOCKED:<reason>` instead of editing it. Out-of-scope "
        "edits will be rejected by the audit-fix path guard "
        "(Phase 3 hook denylist)."
    )
    parts.append(_CLOSE_TAG)

    payload = "\n".join(parts)
    return _bound_payload_size(payload, max_size_bytes)

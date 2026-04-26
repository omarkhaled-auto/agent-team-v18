"""Rule-based scope-drift checks for Codex plan and diff notifications.

Pure Python regex matching. NO Anthropic SDK, NO API calls, NO network.
Every public entrypoint is fail-open: any internal exception returns "".

Future extension: `codex_semantic_check_enabled` flag may add a Haiku
semantic layer. NOT implemented in Phase 5 - do not add imports for it.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

_FRONTEND_FILE_PATTERNS = [
    re.compile(r"apps/web/"),
    re.compile(r"(^|/)pages/"),
    re.compile(r"(^|/)components/"),
    re.compile(r"\.tsx$"),
    re.compile(r"\.jsx$"),
    re.compile(r"\.css$"),
    re.compile(r"tailwind\.config"),
]

_BACKEND_FILE_PATTERNS = [
    re.compile(r"apps/api/"),
    # Wave D may consume the generated client, but it must not edit it.
    re.compile(r"(^|/)packages/api-client/"),
    re.compile(r"(^|/)prisma/"),
    re.compile(r"(^|/)\.env(\.[^/]+)?$"),
    re.compile(r"nest-cli\.json"),
    re.compile(r"\.module\.ts$"),
    re.compile(r"(^|/)Dockerfile(\.|$)"),
    re.compile(r"docker-compose(\.[^/]+)?\.ya?ml$"),
    re.compile(r"\.py$"),
]

_WAVE_FORBIDDEN: dict[str, list[re.Pattern[str]]] = {
    "B": _FRONTEND_FILE_PATTERNS,
    "D": _BACKEND_FILE_PATTERNS,
}

_WAVE_ALLOWED_EXCEPTIONS: dict[str, set[str]] = {
    # M1 foundation can require backend/OpenAPI work to align existing
    # frontend contract configuration. These are not UI implementation files.
    "B": {
        "apps/web/.env.example",
        "apps/web/openapi-ts.config.ts",
        # Wave B Codex sometimes re-emits ``apps/web/package.json`` when
        # running ``pnpm install`` / ``pnpm add`` in the workspace —
        # pnpm reformats the file (sort order / trailing newline) even
        # when no apps/web dep is added. Smoke
        # ``v18 test runs/m1-hardening-smoke-20260425-214325`` failed
        # SCOPE-VIOLATION-001 here. The file is scaffold-owned and
        # tightly constrained by ``scaffold_runner``; treating it as a
        # cross-stack write would require disabling Wave B's right to
        # run pnpm at all, which contradicts how Wave B legitimately
        # adds backend deps. The structural answer is the Codex Wave-B
        # sandbox refactor tracked in
        # ``project_wave_d_sandbox_restriction_followup.md``.
        "apps/web/package.json",
    },
}

_WAVE_ROLE: dict[str, str] = {
    "B": "backend wave (Python/server-side code only)",
    "D": "frontend wave (React/TypeScript UI only)",
}

_DRIFT_THRESHOLD = 2
_SMALL_DIFF_FLOOR = 3

_DIFF_GIT_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)
_DIFF_PLUSPLUS_HEADER = re.compile(r"^\+\+\+ b/(\S+)", re.MULTILINE)


def _forbidden_for(wave_letter: str) -> list[re.Pattern[str]] | None:
    if not isinstance(wave_letter, str):
        return None
    return _WAVE_FORBIDDEN.get(wave_letter.strip().upper())


def _matches_any(path: str, patterns: list[re.Pattern[str]]) -> bool:
    for pat in patterns:
        if pat.search(path):
            return True
    return False


def _is_allowed_exception(path: str, wave_letter: str) -> bool:
    normalized = str(path or "").replace("\\", "/").strip()
    allowed = _WAVE_ALLOWED_EXCEPTIONS.get(str(wave_letter or "").strip().upper())
    if not allowed:
        return False
    if normalized in allowed:
        return True
    for allowed_path in allowed:
        pattern = rf"(?<![A-Za-z0-9_./-]){re.escape(allowed_path)}(?![A-Za-z0-9_./-])"
        if re.search(pattern, normalized):
            return True
    return False


def find_forbidden_paths(paths: Iterable[str], wave_letter: str) -> list[str]:
    """Return changed paths that violate the wave's coarse stack boundary.

    Unlike the observer steer helpers, this runs without drift thresholds so
    post-wave enforcement can fail immediately on the first forbidden write.
    Fail-open: any internal exception returns ``[]``.
    """
    try:
        patterns = _forbidden_for(wave_letter)
        if not patterns:
            return []
        offending: list[str] = []
        seen: set[str] = set()
        for raw in paths:
            path = str(raw or "").replace("\\", "/").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            if _matches_any(path, patterns) and not _is_allowed_exception(
                path,
                wave_letter,
            ):
                offending.append(path)
        return offending
    except Exception:
        logger.warning("codex forbidden-path collection failed (fail-open)", exc_info=True)
        return []


def _steer_message(wave_letter: str, offending: list[str]) -> str:
    role = _WAVE_ROLE.get(wave_letter.upper(), f"wave {wave_letter}")
    sample = ", ".join(f"`{p}`" for p in offending[:3])
    return (
        f"[Observer] Wave {wave_letter.upper()} is the {role}. "
        f"The current step touches out-of-scope files ({sample}). "
        f"Stop editing those and focus on this wave's assigned deliverables only."
    )


def check_codex_plan(plan_lines: list[str], wave_letter: str) -> str:
    """Return a steer message if the plan drifts out of the wave's scope, else "".

    Fail-open: any internal exception returns "".
    """
    try:
        patterns = _forbidden_for(wave_letter)
        if not patterns or not plan_lines:
            return ""
        hits: list[str] = []
        for line in plan_lines:
            if not isinstance(line, str) or not line.strip():
                continue
            if _matches_any(line, patterns) and not _is_allowed_exception(
                line.strip(),
                wave_letter,
            ):
                hits.append(line.strip()[:120])
            if len(hits) >= _DRIFT_THRESHOLD:
                return _steer_message(wave_letter, hits)
        return ""
    except Exception:
        logger.warning("codex plan check failed (fail-open)", exc_info=True)
        return ""


def check_codex_diff(diff_text: str, wave_letter: str) -> str:
    """Return a steer message if the diff shows scope drift, else "".

    Fail-open: any internal exception returns "".
    """
    try:
        patterns = _forbidden_for(wave_letter)
        if not patterns or not isinstance(diff_text, str) or not diff_text:
            return ""

        changed: list[str] = []
        seen: set[str] = set()
        for match in _DIFF_GIT_HEADER.finditer(diff_text):
            path = match.group(2)
            if path and path not in seen:
                seen.add(path)
                changed.append(path)
        if not changed:
            for match in _DIFF_PLUSPLUS_HEADER.finditer(diff_text):
                path = match.group(1)
                if path and path not in seen:
                    seen.add(path)
                    changed.append(path)

        if len(changed) < _SMALL_DIFF_FLOOR:
            return ""

        offending = [
            p
            for p in changed
            if _matches_any(p, patterns) and not _is_allowed_exception(p, wave_letter)
        ]
        if len(offending) >= _DRIFT_THRESHOLD:
            return _steer_message(wave_letter, offending)
        return ""
    except Exception:
        logger.warning("codex diff check failed (fail-open)", exc_info=True)
        return ""

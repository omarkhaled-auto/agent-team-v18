"""Wave ownership classification for audit findings (Phase 4.3).

Plan: ``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §F.

The 2026-04-26 M1 hardening smoke graded all 46 audit findings as if
every wave had executed, even though Waves C/D/T never ran. ≥4 of the
11 critical findings were downstream of "later wave never ran" — Wave
D's frontend chassis (i18n, locales, layout) and Wave C's
api-client. Phase 4.3 closes this by tagging every finding with an
``owner_wave`` derived from its primary file path, exposing a
``DEFERRED`` status when the owner wave didn't execute, and computing
convergence ratios over executed-wave findings only.

Design choices:
* Path → wave map is a small, deterministic table; lookups use prefix
  matching with most-specific-wins ordering.
* ``wave-agnostic`` is the safe fallback — these findings have no
  wave to defer to, so audit-fix dispatch always treats them as
  actionable.
* Wave-letter executed-state reads ``RunState.wave_progress[*]`` —
  both ``completed_waves`` and ``failed_wave`` count as "ran"; only
  waves that NEVER started become DEFERRED. Phase 4.3 explicitly
  preserves the "Wave B failed but ran" case (Wave B findings stay
  FAIL, not DEFERRED) so the audit-fix recovery path Phase 4.5 will
  enable still applies to them.
"""

from __future__ import annotations

from typing import Any, Iterable

__all__ = [
    "WAVE_PATH_OWNERSHIP",
    "WAVE_AGNOSTIC",
    "DEFERRED_STATUS",
    "resolve_owner_wave",
    "is_owner_wave_executed",
    "compute_finding_status",
    "compute_filtered_convergence_ratio",
]


WAVE_AGNOSTIC = "wave-agnostic"
DEFERRED_STATUS = "DEFERRED"


# Ordered (prefix, wave_letter) pairs. Longest prefix wins — the
# resolver iterates in declaration order, so place more-specific
# prefixes first. The table mirrors §F's starter map plus the
# implicit refinements from §B.6 manual classification of the
# 2026-04-26 smoke's 46 findings.
_WAVE_PATH_TABLE: tuple[tuple[str, str], ...] = (
    # Wave D — frontend (apps/web/* incl. locales subdir)
    ("apps/web/", "D"),
    # Wave B — backend + ORM
    ("apps/api/", "B"),
    ("prisma/", "B"),
    # Wave C — shared API client package
    ("packages/api-client/", "C"),
    ("packages/api-client", "C"),  # exact-match on the directory itself
    # Wave T — end-to-end and integration tests
    ("e2e/tests/", "T"),
    ("e2e/", "T"),
    ("tests/", "T"),
)


# Public exposure of the table as a dict for inspection / docs. Order
# is preserved (Python dicts are insertion-ordered since 3.7); callers
# that iterate must respect order for most-specific-wins semantics.
WAVE_PATH_OWNERSHIP: dict[str, str] = dict(_WAVE_PATH_TABLE)


def _normalize_path(path: str | None) -> str:
    """Lower-cost POSIX normalisation for path matching.

    Strips leading slashes and converts Windows separators. Phase 4.3
    accepts paths from audit JSONs ingested across both platforms, so
    the resolver must round-trip identically.
    """
    if not path:
        return ""
    text = str(path).strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def resolve_owner_wave(path: str | None) -> str:
    """Map a file path to a wave letter (B/C/D/T/...) or
    ``wave-agnostic``.

    Empty / None / unresolved paths return ``wave-agnostic`` so the
    audit-fix dispatch never silently swallows a finding by mis-tagging
    it as deferred.
    """
    normalized = _normalize_path(path)
    if not normalized:
        return WAVE_AGNOSTIC
    for prefix, wave in _WAVE_PATH_TABLE:
        if normalized == prefix.rstrip("/"):
            return wave
        if normalized.startswith(prefix):
            return wave
    return WAVE_AGNOSTIC


def _wave_progress_iter(run_state: Any) -> Iterable[dict[str, Any]]:
    """Yield each milestone's wave_progress entry as a plain dict.

    Tolerant of ``None`` and of ``RunState`` instances that haven't
    populated ``wave_progress`` yet — returns an empty iterator in
    that case so callers can treat "no wave info" identically to
    "no waves executed".
    """
    if run_state is None:
        return ()
    progress = getattr(run_state, "wave_progress", None)
    if not isinstance(progress, dict):
        return ()
    return [entry for entry in progress.values() if isinstance(entry, dict)]


def is_owner_wave_executed(
    wave_letter: str,
    run_state: Any,
    *,
    milestone_id: str | None = None,
) -> bool:
    """Has ``wave_letter`` actually started for the named milestone
    (or any milestone if ``milestone_id`` is None)?

    Counts both ``completed_waves`` and ``failed_wave`` — a wave that
    ran-and-failed is still "executed" for the purposes of Phase 4.3
    classification. Only waves that never started become DEFERRED.

    ``wave-agnostic`` is always reported as executed — these findings
    have no wave to defer to, so audit-fix should always be allowed
    to act on them.
    """
    if not wave_letter:
        return False
    if wave_letter == WAVE_AGNOSTIC:
        return True
    if run_state is None:
        return False

    target = str(wave_letter).strip()
    if not target:
        return False

    if milestone_id is not None:
        progress = getattr(run_state, "wave_progress", None)
        if not isinstance(progress, dict):
            return False
        entry = progress.get(milestone_id)
        if not isinstance(entry, dict):
            return False
        candidates = [
            *list(entry.get("completed_waves", []) or []),
            entry.get("failed_wave", ""),
        ]
        return any(str(w).strip() == target for w in candidates if w)

    for entry in _wave_progress_iter(run_state):
        for wave in entry.get("completed_waves", []) or []:
            if str(wave).strip() == target:
                return True
        failed = entry.get("failed_wave")
        if failed and str(failed).strip() == target:
            return True
    return False


def compute_finding_status(finding: Any, run_state: Any) -> str:
    """Compute a finding's effective status under Phase 4.3 semantics.

    Returns ``"DEFERRED"`` when ``finding.owner_wave`` is a wave letter
    whose owner wave never executed. Otherwise returns the finding's
    existing ``verdict`` (``FAIL``/``PASS``/``PARTIAL``/``UNVERIFIED``).
    Used by ``compute_filtered_convergence_ratio`` and by Phase 4.5's
    audit-fix dispatch gate.
    """
    owner_wave = str(getattr(finding, "owner_wave", WAVE_AGNOSTIC) or WAVE_AGNOSTIC)
    if owner_wave != WAVE_AGNOSTIC and not is_owner_wave_executed(owner_wave, run_state):
        return DEFERRED_STATUS
    verdict = getattr(finding, "verdict", "")
    return str(verdict or "FAIL")


def compute_filtered_convergence_ratio(
    findings: list[Any],
    run_state: Any,
) -> float:
    """Convergence ratio over executed-wave findings only.

    Numerator: count of executed-wave findings whose verdict is PASS.
    Denominator: count of executed-wave findings (i.e. findings
    excluding those whose owner_wave never ran).

    Returns 0.0 when the executed-wave set is empty (degenerate input
    — no signal to converge on).
    """
    if not findings:
        return 0.0
    executed: list[Any] = [
        f for f in findings
        if compute_finding_status(f, run_state) != DEFERRED_STATUS
    ]
    if not executed:
        return 0.0
    passed = sum(
        1 for f in executed
        if str(getattr(f, "verdict", "") or "").upper() == "PASS"
    )
    return passed / len(executed)

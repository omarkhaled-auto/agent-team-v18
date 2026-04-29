"""Phase 5.5 §M.M2 — State-invariant validators (two layers).

Two layers split by lifecycle:

* :func:`validate_state_shape_invariants` — cheap intra-STATE rules; called
  from :func:`agent_team_v15.state.save_state` ALWAYS. Returns a list of
  violation messages; the caller logs at WARNING. Does NOT raise so that
  transitional writes in mid-run loops are not bricked.

* :func:`validate_terminal_quality_invariants` — full Quality Contract +
  filesystem invariants. Called only from
  :func:`agent_team_v15.quality_contract._finalize_milestone_with_quality_contract`
  and :func:`agent_team_v15.wave_executor._capture_milestone_anchor_on_complete`.
  Raises :class:`StateInvariantViolation` by default. Migration commands
  (``rescan-quality-debt``, ``confirm-findings``) pass ``warn_only=True``
  so pre-Phase-5 hollow-recovery STATE.json shapes don't brick the
  command — they surface as a violation report instead.

Sentinel-aware (Phase 5.3 AC2): Rule 1 only fires on ``unresolved_findings_count > 0``
AND ``audit_debt_severity in {"CRITICAL","HIGH"}``. Missing keys / ``-1`` / ``""``
defaults do not trip — the Phase 1.6 / 4.4 / 4.5 byte-shape with NO audit_*
keys remains a clean, valid state.

Rule 3 (``forbidden_failed_without_failure_reason``) is **layer-2 only** by
design: hard-execution FAILED sites (architecture gate, preflight, exception
handlers) at ``cli.py:5050/5471/5959/6202/6234`` write FAILED without a
failure_reason today. Layer 1 enforcement would brick existing code; the
Quality Contract semantics only require a reason at quality-dependent
terminal boundaries (resolver / capture). Phase 6+ may retrofit hard-exec
sites if the reason becomes load-bearing for forensics.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .state import StateInvariantError

if TYPE_CHECKING:
    from .state import RunState


class StateInvariantViolation(StateInvariantError):
    """Phase 5.5 §M.M2 — Quality Contract / filesystem invariant violation.

    Subclass of :class:`StateInvariantError` so existing
    ``except StateInvariantError`` blocks catch the new contract violations
    alongside the existing ``summary.success`` invariant. New code raising
    a Quality Contract violation should use this specific subclass; broad
    catchers continue to work.
    """


_HIGH_CRITICAL = frozenset({"CRITICAL", "HIGH"})


# ---------------------------------------------------------------------------
# Per-rule predicates
# ---------------------------------------------------------------------------


def _check_forbidden_complete_with_high_debt(state: "RunState") -> list[str]:
    """Rule 1 — ``status == "COMPLETE"`` AND quality fields say HIGH/CRITICAL debt.

    Sentinel-aware: missing keys / ``unresolved_findings_count == -1`` /
    ``audit_debt_severity == ""`` do NOT trip. Only the explicit
    "completed-with-blocking-debt" shape is a violation.
    """

    out: list[str] = []
    progress = getattr(state, "milestone_progress", None) or {}
    for ms_id, entry in progress.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "COMPLETE":
            continue
        unresolved = entry.get("unresolved_findings_count", -1)
        severity = entry.get("audit_debt_severity", "")
        if unresolved > 0 and severity in _HIGH_CRITICAL:
            out.append(
                f"forbidden_complete_with_high_debt: milestone {ms_id} "
                f"has status=COMPLETE with unresolved_findings_count={unresolved} "
                f"and audit_debt_severity={severity!r}; the Quality Contract (§B) "
                f"requires FAILED for any unresolved FAIL ≥ HIGH on executed waves."
            )
    return out


def _check_forbidden_failed_without_failure_reason(state: "RunState") -> list[str]:
    """Rule 3 — ``status == "FAILED"`` AND ``failure_reason == ""``.

    LAYER 2 ONLY. Hard-execution FAILED sites (architecture gate, preflight,
    exception handlers) don't pass failure_reason today; layer 1 enforcement
    would brick existing code. Layer 2 fires only at quality-dependent
    terminal boundaries where the resolver guarantees a reason.
    """

    out: list[str] = []
    progress = getattr(state, "milestone_progress", None) or {}
    for ms_id, entry in progress.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "FAILED":
            continue
        if not entry.get("failure_reason", ""):
            out.append(
                f"forbidden_failed_without_failure_reason: milestone {ms_id} "
                f"has status=FAILED with empty failure_reason; Phase 1.6 contract "
                f"requires a non-empty reason at quality-dependent FAILED writes."
            )
    return out


def _check_forbidden_anchor_without_quality_sidecar(
    state: "RunState",
    *,
    cwd: Path,
    milestone_id: str,
) -> list[str]:
    """Rule 2 — ``_anchor/_complete/`` on disk for ``milestone_id``
    AND ``_quality.json`` missing.

    LAYER 2 ONLY. Filesystem-aware. Pre-Phase-5.5 anchors have no sidecar,
    so this rule only fires for anchors captured by Phase-5.5+ code.
    Migration commands using ``warn_only=True`` surface this gap without
    bricking the command.
    """

    out: list[str] = []
    anchor_root = (
        Path(cwd) / ".agent-team" / "milestones" / milestone_id / "_anchor" / "_complete"
    )
    if not anchor_root.exists():
        return out
    sidecar = anchor_root / "_quality.json"
    if not sidecar.is_file():
        out.append(
            f"forbidden_anchor_without_quality_sidecar: milestone {milestone_id} "
            f"has _anchor/_complete/ at {anchor_root.as_posix()} but missing "
            f"_quality.json sidecar."
        )
    return out


# ---------------------------------------------------------------------------
# Layer 1 — shape invariants (cheap, save_state always)
# ---------------------------------------------------------------------------


def validate_state_shape_invariants(state: "RunState") -> list[str]:
    """Phase 5.5 §M.M2 layer 1 — cheap intra-STATE invariants from save_state.

    Returns a list of violation messages; the caller logs at WARNING. Does
    NOT raise — transitional writes in mid-run audit-fix loops must not
    brick on rules that are only fully realized at terminal-finalize time.

    Includes only Rule 1 (``forbidden_complete_with_high_debt``). Rule 2
    requires filesystem access (cwd + milestone_id). Rule 3 is
    layer-2-only (hard-exec FAILED sites are exempt).
    """

    return _check_forbidden_complete_with_high_debt(state)


# ---------------------------------------------------------------------------
# Layer 2 — terminal quality invariants (resolver/capture, raises by default)
# ---------------------------------------------------------------------------


def validate_terminal_quality_invariants(
    state: "RunState",
    *,
    cwd: Path,
    milestone_id: str,
    warn_only: bool = False,
) -> list[str]:
    """Phase 5.5 §M.M2 layer 2 — full Quality Contract + filesystem invariants.

    Called from:

    * :func:`agent_team_v15.quality_contract._finalize_milestone_with_quality_contract`
    * :func:`agent_team_v15.wave_executor._capture_milestone_anchor_on_complete`
    * ``rescan-quality-debt`` cli (with ``warn_only=True``)
    * ``confirm-findings`` cli (with ``warn_only=True``)

    Rules: 1 (state shape) + 2 (anchor/sidecar) + 3 (FAILED+reason).

    Default raises :class:`StateInvariantViolation` on any violation. With
    ``warn_only=True`` returns the list of violations and does NOT raise.
    """

    violations: list[str] = []
    violations.extend(_check_forbidden_complete_with_high_debt(state))
    violations.extend(_check_forbidden_failed_without_failure_reason(state))
    violations.extend(
        _check_forbidden_anchor_without_quality_sidecar(
            state, cwd=Path(cwd), milestone_id=milestone_id,
        )
    )
    if violations and not warn_only:
        raise StateInvariantViolation("; ".join(violations))
    return violations


# ---------------------------------------------------------------------------
# Rule registry (for §M.M2 lint test)
# ---------------------------------------------------------------------------

KNOWN_RULES: tuple[str, ...] = (
    "forbidden_complete_with_high_debt",
    "forbidden_failed_without_failure_reason",
    "forbidden_anchor_without_quality_sidecar",
)


__all__ = (
    "StateInvariantViolation",
    "validate_state_shape_invariants",
    "validate_terminal_quality_invariants",
    "KNOWN_RULES",
)

"""Phase 5.4 — fix-regression workspace rollback (R-#35 + §M.M14).

The audit-fix loop pre-Phase-5.4 had two rollback layers:

* In-memory ``_snapshot_files`` keyed on the file paths named in the
  current ``AuditReport.findings`` (cli.py). Score-only regression check;
  cannot capture a file fix-Claude *creates* outside the finding set, and
  cannot detect a regression that adds a new compile-profile diagnostic
  while keeping the score flat.
* Phase 1 milestone anchor restore (``_handle_audit_failure_milestone_anchor``)
  for the regression / no_improvement audit-loop terminate branch. Whole-
  milestone rollback; too coarse for "fix dispatch introduced one new
  compile-profile diagnostic".

§M.M14 (plan v5) adds a third layer between them: a per-dispatch
diagnostic-identity comparison. Capture the full workspace + the
full-workspace TypeScript compile profile BEFORE each
``_run_audit_fix_unified`` dispatch; capture the same AFTER. If the
post-dispatch diagnostics contain at least one identity (file, line,
code, normalized message) NOT present pre-dispatch, the dispatch
regressed: restore every modified file, recreate every deleted file,
and remove every created file.

The rollback machinery is the existing checkpoint walker
(``wave_executor._create_checkpoint`` + ``_diff_checkpoints``) paired
with the byte-snapshot pair from ``provider_router``
(``snapshot_for_rollback`` + ``rollback_from_snapshot``). Reusing those
keeps the skip-filter semantics aligned (``.git``, ``.agent-team``,
``node_modules``, ``.next``, etc. are skipped in both walkers; gitkeep
files are ignored). The workspace-rollback path therefore works
identically on a workspace with no ``.git`` directory — relevant for
synthetic test fixtures and for partially-bootstrapped milestone runs
where ``git init`` hasn't fired yet.

Public contract:

* :func:`capture_pre_dispatch_state` — snapshot files + diagnostics
  before the dispatch. Returns an opaque ``PreDispatchState`` the
  caller threads back into :func:`detect_and_rollback_regression`.
* :func:`detect_and_rollback_regression` — async; runs the full-
  workspace compile profile, compares identities to the pre-state.
  Restores the workspace if any new identity appeared. Returns a
  :class:`RollbackOutcome` with the list of new diagnostics + restore
  counts so the caller can log + persist telemetry.

Anti-patterns (locked by §G.7 + §M.M14 implementation note):

* DO NOT use ``git diff`` against HEAD. The audit-fix loop runs in
  workspaces that may not be a git repository (e.g., ``tests/fixtures/``
  shapes); moreover, a clean ``git diff`` does not reflect post-tool
  unstaged edits the audit-fix Claude session writes. Use the
  checkpoint walker.
* DO NOT use the ``compile_profiles`` "fallback for unknown wave"
  branch. That selects only ``backend`` + ``shared`` tsconfigs and
  silently misses every frontend / generated-client diagnostic — which
  is exactly the class §M.M14 #3 fixture exists to catch. Use
  ``wave="E"`` to force the full-workspace profile.
* DO NOT count-only compare diagnostics. A fix-Claude session that
  trades one diagnostic for a different one keeps the count steady but
  introduces a new identity. §M.M14 #3 locks this contract.

Phase 5.5 will refine the workspace-rollback into the Quality Contract
finalize helper (§M.M1). Phase 5.4 ships the layer; Phase 5.5 wires it
into the single resolver.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .compile_profiles import CompileProfile, run_wave_compile_check
from .provider_router import rollback_from_snapshot, snapshot_for_rollback
from .wave_executor import (
    CheckpointDiff,
    WaveCheckpoint,
    _create_checkpoint,
    _diff_checkpoints,
)

if TYPE_CHECKING:  # pragma: no cover — import-time only
    from .compile_profiles import CompileResult

logger = logging.getLogger(__name__)


# Diagnostic identity tuple shape: (file, line, code, normalized_message).
# ``file`` is the relative POSIX path the parser produced; ``line`` is
# the integer line number (0 when absent); ``code`` is the typescript
# error code (e.g. ``"TS2304"``) or sentinel like ``"ENV_NOT_READY"``;
# ``normalized_message`` is the message with whitespace runs collapsed
# and trailing punctuation stripped so trivial scorer-LLM/tsc rewording
# doesn't false-positive a new identity.
DiagnosticIdentity = tuple[str, int, str, str]


@dataclass(frozen=True)
class PreDispatchState:
    """Opaque payload threaded through ``capture_pre_dispatch_state`` →
    ``detect_and_rollback_regression``.

    Holds enough state to detect the §M.M14 fix-regression class AND to
    perform a full workspace rollback when one fires. Frozen so the
    audit-loop callers cannot accidentally mutate it between capture and
    detect.
    """

    workspace_dir: Path
    pre_checkpoint: WaveCheckpoint
    pre_snapshot: dict[str, bytes]
    pre_diagnostics: frozenset[DiagnosticIdentity]
    pre_diagnostics_available: bool


@dataclass
class RollbackOutcome:
    """Result of ``detect_and_rollback_regression``.

    Telemetry the caller logs / persists when a rollback fires. When
    ``rollback_fired`` is False the caller continues the audit-loop;
    when True the caller breaks the loop AND lets the Phase 4.5
    epilogue run on the rolled-back workspace (per §M.M14 implementation
    note).
    """

    rollback_fired: bool = False
    new_diagnostic_identities: list[DiagnosticIdentity] = field(default_factory=list)
    diff: CheckpointDiff | None = None
    pre_diagnostics_available: bool = True
    post_diagnostics_available: bool = True
    restore_skipped_reason: str = ""


def _normalize_message(raw: object) -> str:
    """Collapse whitespace + drop trailing punctuation so scorer-LLM/tsc
    rewording can't false-positive a new diagnostic identity.
    """
    text = str(raw or "")
    # Collapse whitespace runs (including newlines) into single spaces.
    parts = text.split()
    normalized = " ".join(parts).strip()
    # Drop trailing periods so "foo bar" and "foo bar." compare equal.
    while normalized.endswith("."):
        normalized = normalized[:-1].rstrip()
    return normalized


def _full_workspace_compile_profile() -> CompileProfile:
    """Force the full-workspace TypeScript profile.

    The default ``run_wave_compile_check`` resolver dispatches via
    ``_get_typescript_profile(wave, template, root)``; an empty wave
    string falls into the ``else:`` branch at compile_profiles.py:273+
    which selects only ``backend`` + ``shared`` tsconfigs (per the
    Phase 5.4 team-lead correction). For §M.M14 we need every frontend
    / generated-client diagnostic too, so use the wave="E" /"T" path's
    ``typescript_full_workspace_wave_E`` profile. We pre-build the
    profile here so the per-call ``run_wave_compile_check`` invocation
    bypasses the resolver entirely (and stays stable across template
    drift).
    """
    return CompileProfile(
        name="typescript_full_workspace_audit_fix_rollback",
        commands=[["npx", "tsc", "--noEmit", "--pretty", "false"]],
        description=(
            "Full-workspace TypeScript compile for §M.M14 fix-regression "
            "diagnostic-identity capture (Phase 5.4 audit_fix_rollback)."
        ),
    )


def _diagnostics_to_identities(
    compile_result: "CompileResult | None",
) -> frozenset[DiagnosticIdentity]:
    """Project a :class:`CompileResult` into a set of stable identities."""
    if compile_result is None:
        return frozenset()
    identities: set[DiagnosticIdentity] = set()
    for err in getattr(compile_result, "errors", None) or []:
        if not isinstance(err, dict):
            continue
        try:
            line_val = int(err.get("line", 0) or 0)
        except (TypeError, ValueError):
            line_val = 0
        identities.add((
            str(err.get("file", "") or ""),
            line_val,
            str(err.get("code", "") or ""),
            _normalize_message(err.get("message", "")),
        ))
    return frozenset(identities)


async def _run_full_workspace_diagnostics(
    workspace_dir: Path,
) -> tuple[frozenset[DiagnosticIdentity], bool]:
    """Run the full-workspace compile profile and project to identities.

    Returns ``(identities, available)``. ``available`` is False on:

    * Workspace doesn't contain a root ``tsconfig.json`` (no profile
      to run; §M.M14 doesn't apply to non-TS workspaces).
    * The compile invocation itself failed in a way that means we
      cannot trust the parsed errors (e.g. ``MISSING_COMMAND``,
      ``ENV_NOT_READY``, ``TIMEOUT``).

    When ``available`` is False the identity comparison is skipped and
    the existing in-memory ``_snapshot_files`` rollback (legacy score-
    only) remains the sole regression detector — which is the
    pre-Phase-5.4 behaviour. This is intentional: we don't want to
    refuse to dispatch when the diagnostic capture is structurally
    impossible.
    """
    root_tsconfig = workspace_dir / "tsconfig.json"
    if not root_tsconfig.is_file():
        return frozenset(), False

    profile = _full_workspace_compile_profile()
    try:
        result = await run_wave_compile_check(str(workspace_dir), profile)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "audit_fix_rollback: full-workspace compile invocation failed: %s",
            exc,
        )
        return frozenset(), False

    # Treat infrastructure-class errors (env-not-ready, missing command,
    # timeout) as "diagnostics not available" rather than synthesising a
    # rollback signal from them. The error parser flags those with
    # specific code sentinels.
    infra_codes = {"MISSING_COMMAND", "ENV_NOT_READY", "TIMEOUT"}
    if result.errors:
        observed = {str(err.get("code", "") or "") for err in result.errors if isinstance(err, dict)}
        if observed and observed.issubset(infra_codes):
            return frozenset(), False

    return _diagnostics_to_identities(result), True


def capture_pre_dispatch_state_sync(workspace_dir: Path) -> PreDispatchState:
    """Synchronous helper that snapshots the workspace + checkpoint only.

    Used by the §M.M14 #2 fixture (partial-success preserved) where the
    diagnostic capture is mocked. Production callers use
    :func:`capture_pre_dispatch_state` (async) which also captures
    diagnostics.
    """
    pre_checkpoint = _create_checkpoint("audit-fix-pre-dispatch", str(workspace_dir))
    pre_snapshot = snapshot_for_rollback(str(workspace_dir), pre_checkpoint)
    return PreDispatchState(
        workspace_dir=workspace_dir,
        pre_checkpoint=pre_checkpoint,
        pre_snapshot=pre_snapshot,
        pre_diagnostics=frozenset(),
        pre_diagnostics_available=False,
    )


async def capture_pre_dispatch_state(workspace_dir: Path) -> PreDispatchState:
    """Capture workspace + diagnostics before fix dispatch.

    The capture is best-effort: if the workspace has no ``tsconfig.json``
    (non-TS project, or scaffold not yet bootstrapped), the diagnostic
    set comes back empty and ``pre_diagnostics_available`` is False —
    detection in :func:`detect_and_rollback_regression` then short-
    circuits to the legacy score-only path.
    """
    pre_checkpoint = _create_checkpoint("audit-fix-pre-dispatch", str(workspace_dir))
    pre_snapshot = snapshot_for_rollback(str(workspace_dir), pre_checkpoint)
    pre_identities, available = await _run_full_workspace_diagnostics(workspace_dir)
    return PreDispatchState(
        workspace_dir=workspace_dir,
        pre_checkpoint=pre_checkpoint,
        pre_snapshot=pre_snapshot,
        pre_diagnostics=pre_identities,
        pre_diagnostics_available=available,
    )


async def detect_and_rollback_regression(
    pre_state: PreDispatchState,
) -> RollbackOutcome:
    """Detect §M.M14 fix-regression and roll back if needed.

    Workflow:

    1. Capture post-dispatch full-workspace compile diagnostics.
    2. If both pre- and post-diagnostics are unavailable, return
       ``rollback_fired=False`` with both ``*_available`` flags False
       so the caller knows to fall back to the legacy score-only path.
    3. Compute the new-identity set ``post - pre``.
    4. If ``new_identities`` is empty, return ``rollback_fired=False``
       (the dispatch may still be partial-success — fixed N findings
       without introducing new diagnostics; the cycle continues).
    5. If non-empty, capture a post-checkpoint, diff against pre, then
       call :func:`rollback_from_snapshot` to restore modified files,
       recreate deleted files, and remove created files. Return
       ``rollback_fired=True`` with the new-identity list + diff for
       caller telemetry.

    The diagnostic identity is ``(file, line, code, normalized_message)``
    — count-only comparison is insufficient (§M.M14 #3 locks this).
    """
    post_identities, post_available = await _run_full_workspace_diagnostics(
        pre_state.workspace_dir,
    )
    if not pre_state.pre_diagnostics_available and not post_available:
        return RollbackOutcome(
            rollback_fired=False,
            pre_diagnostics_available=False,
            post_diagnostics_available=False,
            restore_skipped_reason="diagnostics_unavailable",
        )
    # If pre was available but post isn't, treat as "infrastructure
    # broke during dispatch" — fail safe: do NOT roll back from
    # incomplete signal. The caller's existing snapshot/regression
    # plumbing handles unsafe states elsewhere.
    if not post_available:
        return RollbackOutcome(
            rollback_fired=False,
            pre_diagnostics_available=pre_state.pre_diagnostics_available,
            post_diagnostics_available=False,
            restore_skipped_reason="post_diagnostics_unavailable",
        )
    # Symmetric: pre wasn't available but post is. We have nothing to
    # diff against; let the dispatch stand. Phase 5.5's Quality
    # Contract evaluator will catch any escaped findings at finalize.
    if not pre_state.pre_diagnostics_available:
        return RollbackOutcome(
            rollback_fired=False,
            pre_diagnostics_available=False,
            post_diagnostics_available=True,
            restore_skipped_reason="pre_diagnostics_unavailable",
        )

    new_identities = sorted(post_identities - pre_state.pre_diagnostics)
    if not new_identities:
        return RollbackOutcome(
            rollback_fired=False,
            pre_diagnostics_available=True,
            post_diagnostics_available=True,
        )

    post_checkpoint = _create_checkpoint(
        "audit-fix-post-dispatch", str(pre_state.workspace_dir),
    )
    diff = _diff_checkpoints(pre_state.pre_checkpoint, post_checkpoint)
    rollback_from_snapshot(
        str(pre_state.workspace_dir),
        pre_state.pre_snapshot,
        pre_state.pre_checkpoint,
        post_checkpoint,
        _diff_checkpoints,
    )
    return RollbackOutcome(
        rollback_fired=True,
        new_diagnostic_identities=list(new_identities),
        diff=diff,
        pre_diagnostics_available=True,
        post_diagnostics_available=True,
    )


def diagnostics_to_identities_for_test(compile_result: Any) -> frozenset[DiagnosticIdentity]:
    """Public-for-test wrapper around the private projector.

    Phase 5.4 fixtures use this to assert identity-tuple shape without
    importing the leading-underscore name.
    """
    return _diagnostics_to_identities(compile_result)


__all__ = [
    "DiagnosticIdentity",
    "PreDispatchState",
    "RollbackOutcome",
    "capture_pre_dispatch_state",
    "capture_pre_dispatch_state_sync",
    "detect_and_rollback_regression",
    "diagnostics_to_identities_for_test",
]

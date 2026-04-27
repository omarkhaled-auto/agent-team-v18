"""Phase 4.4 — deterministic wave-fail forensics.

On wave-fail, the milestone is known broken and a fresh LLM audit
dispatch produces foregone-conclusion findings (~$5-8 burned per
wave-fail in the 2026-04-26 smoke). This module composes the same
information the audit would have surfaced — from already-captured
signal — and writes it to ``.agent-team/WAVE_FAILURE_FORENSICS.json``
in well under a second of pure-Python work.

Inputs sourced from the wave pipeline:

* **Phase 4.1** wired ``WaveFinding.file`` to the failing compose
  service (e.g. ``"web"`` for the 2026-04-26 retry-2 entry). The last
  ``WAVE-<X>-SELF-VERIFY`` finding on the failed wave's ``WaveResult``
  carries the per-service attribution; that becomes
  ``self_verify_error``.
* **Phase 4.2** wired ``WaveResult.last_retry_prompt_suffix`` to the
  most recent ``<previous_attempt_failed>`` block produced by
  ``retry_feedback.build_retry_payload``. That string is the most
  actionable signal we had right before declaring the wave failed; it
  becomes ``structured_retry_feedback.payload``.
* **Phase 4.3** tags every audit finding with ``owner_wave``. When
  ``audit_findings`` are supplied (Phase 4.5+ context where the audit
  pass ran before the wave-fail bypass), the per-wave count is computed
  from ``finding.owner_wave``. When the audit hasn't run yet (Phase
  4.4 hot path), the fallback aggregates ``WAVE_FINDINGS.json`` by the
  per-finding ``wave`` field — at least the wave-self-verify entries
  are wave-attributed by Phase 4.1.

The forensics file is written sorted-keys + indented for human
readability; downstream programmatic consumers should use
``json.load`` / round-trip via ``WaveFailureForensics.from_dict``
rather than parsing the formatted text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_CODEX_LOG_TAIL_BYTES = 8192


@dataclass
class WaveFailureForensics:
    """Schema for ``.agent-team/WAVE_FAILURE_FORENSICS.json``.

    Every field is optional with a safe default so a partial-evidence
    case (e.g. wave_result lacking findings, missing protocol log)
    still produces a usable forensics file. Consumers that need a
    specific field should check truthiness first.
    """

    failed_wave_letter: str = ""
    retry_count: int = 0
    self_verify_error: dict[str, Any] = field(default_factory=dict)
    structured_retry_feedback: dict[str, Any] = field(default_factory=dict)
    files_modified: list[str] = field(default_factory=list)
    codex_protocol_log_tail: str = ""
    docker_compose_ps: str = ""
    owner_wave_findings_count_per_wave: dict[str, int] = field(default_factory=dict)
    failure_reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe ``dict``."""
        return asdict(self)


def build_wave_failure_forensics(
    *,
    wave_result: Any,
    run_state: Any = None,
    audit_findings: list[Any] | None = None,
    wave_findings_path: Path | str | None = None,
    codex_protocol_path: Path | str | None = None,
    docker_compose_ps: str | None = None,
    failure_reason: str = "",
    codex_log_tail_bytes: int = _DEFAULT_CODEX_LOG_TAIL_BYTES,
) -> WaveFailureForensics:
    """Compose a :class:`WaveFailureForensics` from already-captured signal.

    Parameters
    ----------
    wave_result : Any
        ``MilestoneWaveResult``-shaped object. The failed wave is found
        by matching ``wave_result.error_wave`` against
        ``wave_result.waves[*].wave``.
    run_state : Any, optional
        ``RunState`` (unused by Phase 4.4 today; reserved for Phase 4.5+
        when the recovery cascade may need ``wave_progress`` lookups).
    audit_findings : list[Any] | None, optional
        Phase 4.3-tagged findings (each with ``owner_wave``). When
        supplied, ``owner_wave_findings_count_per_wave`` aggregates over
        these. When ``None`` and ``wave_findings_path`` is supplied,
        the fallback aggregates over WAVE_FINDINGS.json's per-finding
        ``wave`` field.
    wave_findings_path : Path | str | None, optional
        Path to ``WAVE_FINDINGS.json``. Used when ``audit_findings`` is
        ``None``. When the file does not exist, the breakdown is
        empty (no audit-time data available yet).
    codex_protocol_path : Path | str | None, optional
        Path to the failed wave's Codex protocol log
        (``.agent-team/codex-captures/milestone-<id>-wave-<X>-protocol.log``).
        Tailed to ``codex_log_tail_bytes`` (default 8 KB) so forensics
        stays forensics-sized regardless of the source log volume.
    docker_compose_ps : str | None, optional
        Captured ``docker compose ps`` output at wave-fail time.
        Recorded verbatim (no parsing) so operators can inspect
        container state post-mortem without re-running the command.
    failure_reason : str, default ``""``
        Mirrors ``RunState.milestone_progress[id]["failure_reason"]``
        (Phase 1.6 + Phase 4.4 wiring). Carried into the forensics so
        operators reading the JSON alone get the same signal as readers
        of STATE.json.
    codex_log_tail_bytes : int, default 8192
        Bound on ``codex_protocol_log_tail``'s byte length. Smoke logs
        can exceed 4 MB; the forensics file should stay forensics-sized
        not log-sized.
    """
    forensics = WaveFailureForensics(
        timestamp=datetime.now(timezone.utc).isoformat(),
        failure_reason=str(failure_reason or ""),
    )

    if wave_result is None:
        return forensics

    failed_letter = str(getattr(wave_result, "error_wave", "") or "").strip().upper()
    forensics.failed_wave_letter = failed_letter

    failed_wave_state = _find_failed_wave_state(wave_result, failed_letter)
    if failed_wave_state is not None:
        sv_findings = _extract_self_verify_findings(failed_wave_state, failed_letter)
        forensics.retry_count = len(sv_findings)
        if sv_findings:
            last = sv_findings[-1]
            forensics.self_verify_error = {
                "code": str(getattr(last, "code", "") or ""),
                "severity": str(getattr(last, "severity", "") or ""),
                "file": str(getattr(last, "file", "") or ""),
                "line": int(getattr(last, "line", 0) or 0),
                "message": str(getattr(last, "message", "") or ""),
            }

        last_suffix = str(
            getattr(failed_wave_state, "last_retry_prompt_suffix", "") or ""
        )
        if last_suffix:
            forensics.structured_retry_feedback = {
                "wave_letter": failed_letter,
                "retry_index": (
                    forensics.retry_count - 1 if forensics.retry_count else 0
                ),
                "payload": last_suffix,
                "payload_size_bytes": len(last_suffix.encode("utf-8")),
            }

        forensics.files_modified = list(
            (getattr(failed_wave_state, "files_created", []) or [])
        ) + list(
            (getattr(failed_wave_state, "files_modified", []) or [])
        )

    forensics.codex_protocol_log_tail = _read_log_tail(
        codex_protocol_path, codex_log_tail_bytes,
    )

    if docker_compose_ps:
        forensics.docker_compose_ps = str(docker_compose_ps)

    forensics.owner_wave_findings_count_per_wave = _aggregate_owner_wave_counts(
        audit_findings, wave_findings_path,
    )

    return forensics


def write_wave_failure_forensics(
    forensics: WaveFailureForensics,
    agent_team_dir: Path | str,
) -> Path:
    """Write ``forensics`` to ``<agent_team_dir>/WAVE_FAILURE_FORENSICS.json``.

    The parent directory is created if missing. JSON output is sorted-
    keys + indented for human readability; readers should round-trip via
    ``json.loads`` rather than parsing the formatted text.

    Returns the path written.
    """
    target = Path(agent_team_dir) / "WAVE_FAILURE_FORENSICS.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(forensics.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _find_failed_wave_state(wave_result: Any, failed_letter: str) -> Any:
    """Return the failed ``WaveResult`` (Phase 4.1+ shape) inside ``wave_result``.

    Falls back to ``wave_result.waves[-1]`` when ``error_wave`` doesn't
    match any wave (degraded path observed when wave_executor sets
    success=False without populating error_wave).
    """
    waves = getattr(wave_result, "waves", []) or []
    if failed_letter:
        for w in waves:
            if str(getattr(w, "wave", "") or "").strip().upper() == failed_letter:
                return w
    if waves:
        return waves[-1]
    return None


def _extract_self_verify_findings(
    wave_state: Any, failed_letter: str,
) -> list[Any]:
    """Return the per-attempt ``WAVE-<X>-SELF-VERIFY`` findings, in order.

    Phase 4.1 + Phase 4.2 append one entry per retry to
    ``wave_state.findings``; the last entry is the FINAL attempt that
    declared the wave failed. Filters out the env-unavailable variant
    so the retry_count reflects code-fail attempts only.
    """
    target_code = f"WAVE-{failed_letter}-SELF-VERIFY"
    out: list[Any] = []
    for f in getattr(wave_state, "findings", []) or []:
        if str(getattr(f, "code", "") or "") == target_code:
            out.append(f)
    return out


def _read_log_tail(
    path: Path | str | None, max_bytes: int,
) -> str:
    """Read the last ``max_bytes`` of the file at ``path`` as UTF-8.

    Returns ``""`` when ``path`` is ``None``, missing, or unreadable.
    Decoding uses ``errors="replace"`` so bytes that don't form valid
    UTF-8 (mid-codepoint truncation at the seek boundary, embedded
    binary in the protocol log) are preserved as replacement chars
    rather than raising.
    """
    if path is None:
        return ""
    log_path = Path(path)
    if not log_path.is_file():
        return ""
    try:
        size = log_path.stat().st_size
        with log_path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            tail_bytes = fh.read()
    except OSError as exc:  # pragma: no cover — defensive
        logger.debug("Failed to read codex protocol log tail at %s: %s", log_path, exc)
        return ""
    return tail_bytes.decode("utf-8", errors="replace")


def _aggregate_owner_wave_counts(
    audit_findings: list[Any] | None,
    wave_findings_path: Path | str | None,
) -> dict[str, int]:
    """Aggregate finding counts by wave attribution.

    Prefers Phase 4.3-tagged AuditFinding objects when supplied
    (counts via ``finding.owner_wave``; falls back to
    ``wave_ownership.resolve_owner_wave`` on the primary file path
    when the field is empty). Falls back to WAVE_FINDINGS.json (the
    only wave-attributed evidence available before the audit fires)
    when ``audit_findings`` is None.
    """
    counts: dict[str, int] = {}
    if audit_findings:
        try:
            from .wave_ownership import resolve_owner_wave
        except ImportError:  # pragma: no cover — defensive
            resolve_owner_wave = None  # type: ignore[assignment]
        for finding in audit_findings:
            owner = str(getattr(finding, "owner_wave", "") or "").strip()
            if not owner and resolve_owner_wave is not None:
                file_path = (
                    str(getattr(finding, "file_path", "") or "")
                    or str(getattr(finding, "file", "") or "")
                )
                owner = resolve_owner_wave(file_path) if file_path else "wave-agnostic"
            owner = owner or "wave-agnostic"
            counts[owner] = counts.get(owner, 0) + 1
        return counts

    if wave_findings_path is None:
        return counts
    findings_path = Path(wave_findings_path)
    if not findings_path.is_file():
        return counts
    try:
        data = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to load WAVE_FINDINGS at %s: %s", findings_path, exc)
        return counts
    if not isinstance(data, dict):
        return counts
    findings = data.get("findings", []) or []
    for f in findings:
        if not isinstance(f, dict):
            continue
        wave_letter = str(f.get("wave", "") or "").strip().upper()
        if wave_letter:
            counts[wave_letter] = counts.get(wave_letter, 0) + 1
    return counts

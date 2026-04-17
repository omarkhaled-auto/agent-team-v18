"""Phase F §7.10 — user-facing confidence banners across ALL reports.

Extends Phase C's D-14 fidelity labels (which stamped four verification
artefacts) to the full user-facing surface:

  * ``AUDIT_REPORT.json`` — ``confidence`` field + reasoning
  * ``BUILD_LOG.txt`` — header line with final confidence
  * ``GATE_*_REPORT.md`` — explicit confidence + reasoning section
  * ``*_RECOVERY_REPORT.md`` — same banner as gate reports

Operators triaging a finished run should see a consistent trust signal
on every artefact, not just the four D-14 ones. Confidence is derived
deterministically from observable signals:

  * evidence_mode (disabled | record_only | soft_gate)
  * how many post-Wave-E scanners ran vs total scanners available
  * did the fix loop converge or plateau
  * was there a runtime verification (compose came up) or not

The helper stays structural: it never writes a "CONFIDENT" badge on
top of missing evidence — that's the whole point of the banner.

Flag ``v18.confidence_banners_enabled`` gates every emission. Default
True; set False to restore pre-Phase-F byte-identical output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


CONFIDENCE_CONFIDENT = "CONFIDENT"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"


@dataclass
class ConfidenceSignals:
    """Deterministic signals used to derive a confidence verdict."""

    evidence_mode: str = "disabled"  # "disabled" | "record_only" | "soft_gate"
    scanners_run: int = 0
    scanners_total: int = 0
    fix_loop_converged: bool = False
    fix_loop_plateaued: bool = False
    runtime_verification_ran: bool = False
    reasoning_notes: list[str] = field(default_factory=list)


def confidence_banners_enabled(config: Any) -> bool:
    v18 = getattr(config, "v18", None)
    return bool(getattr(v18, "confidence_banners_enabled", True))


def derive_confidence(signals: ConfidenceSignals) -> tuple[str, str]:
    """Derive ``(label, reasoning)`` from observable signals.

    Rules (ordered):
      1. ``soft_gate`` evidence mode + converged + all scanners ran +
         runtime verification ran → CONFIDENT.
      2. ``record_only`` or ``disabled`` evidence mode, regardless of
         fix-loop state → MEDIUM (missing evidence gates means we
         cannot positively confirm behaviour).
      3. Fix loop plateaued (not converged) OR < 50% of scanners ran
         OR no runtime verification → LOW.
      4. Otherwise MEDIUM.

    The reasoning string is a plain-English explanation that operators
    will read — avoid jargon, reference the literal signals.
    """
    mode = (signals.evidence_mode or "disabled").strip().lower()
    scanner_ratio = 0.0
    if signals.scanners_total > 0:
        scanner_ratio = signals.scanners_run / signals.scanners_total

    parts: list[str] = [f"evidence_mode={mode}"]
    parts.append(
        f"{signals.scanners_run}/{signals.scanners_total} post-Wave-E scanners ran"
    )
    if signals.fix_loop_converged:
        parts.append("fix loop converged")
    elif signals.fix_loop_plateaued:
        parts.append("fix loop plateaued (no convergence)")
    if signals.runtime_verification_ran:
        parts.append("runtime verification ran")
    else:
        parts.append("runtime verification skipped or blocked")
    parts.extend(signals.reasoning_notes)
    reasoning = "; ".join(parts) + "."

    if signals.fix_loop_plateaued and not signals.fix_loop_converged:
        return CONFIDENCE_LOW, reasoning
    if scanner_ratio > 0 and scanner_ratio < 0.5:
        return CONFIDENCE_LOW, reasoning
    if mode == "soft_gate" and signals.fix_loop_converged and (
        signals.scanners_total == 0 or scanner_ratio >= 0.99
    ) and signals.runtime_verification_ran:
        return CONFIDENCE_CONFIDENT, reasoning
    if mode in ("disabled", "record_only"):
        return CONFIDENCE_MEDIUM, reasoning
    return CONFIDENCE_MEDIUM, reasoning


def format_markdown_banner(label: str, reasoning: str) -> str:
    """Format the MD banner block used by gate / recovery reports."""
    return (
        f"## Confidence: {label}\n"
        f"**Reasoning:** {reasoning}\n"
    )


def format_log_banner(label: str, reasoning: str) -> str:
    """Single-line banner for BUILD_LOG.txt headers."""
    return f"[CONFIDENCE={label}] {reasoning}\n"


def stamp_markdown_report(
    path: str | Path,
    *,
    label: str,
    reasoning: str,
) -> bool:
    """Prepend / update the confidence banner on a markdown artefact.

    Idempotent: repeated calls with the same file upgrade the label and
    reasoning in place rather than stacking banners. Returns True when
    the file was modified, False when unchanged or missing.
    """
    target = Path(path)
    if not target.is_file():
        return False
    try:
        existing = target.read_text(encoding="utf-8")
    except OSError:
        return False
    anchor = "## Confidence:"
    banner = format_markdown_banner(label, reasoning)
    if anchor in existing[:1000]:
        # Replace the existing banner line + its following reasoning
        # line so the banner never drifts from the underlying signals.
        lines = existing.splitlines(keepends=True)
        out: list[str] = []
        skip_next = False
        replaced = False
        for line in lines:
            if skip_next:
                skip_next = False
                continue
            if not replaced and line.lstrip().startswith(anchor):
                out.append(banner)
                # The line immediately after is expected to be the
                # ``**Reasoning:** ...`` line emitted by this helper.
                # Drop it if present so we don't duplicate reasoning.
                replaced = True
                skip_next = True
                continue
            out.append(line)
        new_content = "".join(out)
        if new_content == existing:
            return False
        try:
            target.write_text(new_content, encoding="utf-8")
        except OSError:
            return False
        return True
    try:
        target.write_text(banner + "\n" + existing, encoding="utf-8")
    except OSError:
        return False
    return True


def stamp_build_log(
    path: str | Path,
    *,
    label: str,
    reasoning: str,
) -> bool:
    """Ensure BUILD_LOG.txt has a ``[CONFIDENCE=...]`` header line.

    Idempotent: if a ``[CONFIDENCE=`` line exists within the first 2 KB
    it is replaced in place rather than duplicated.
    """
    target = Path(path)
    if not target.is_file():
        return False
    try:
        existing = target.read_text(encoding="utf-8")
    except OSError:
        return False
    new_line = format_log_banner(label, reasoning)
    head = existing[:2048]
    if "[CONFIDENCE=" in head:
        # Replace only the first occurrence to keep semantics stable.
        lines = existing.splitlines(keepends=True)
        replaced = False
        out: list[str] = []
        for line in lines:
            if not replaced and "[CONFIDENCE=" in line:
                out.append(new_line)
                replaced = True
                continue
            out.append(line)
        new_content = "".join(out)
    else:
        new_content = new_line + existing
    if new_content == existing:
        return False
    try:
        target.write_text(new_content, encoding="utf-8")
    except OSError:
        return False
    return True


def stamp_json_report(
    path: str | Path,
    *,
    label: str,
    reasoning: str,
) -> bool:
    """Add a ``confidence`` / ``confidence_reasoning`` key to a JSON file.

    Works on AUDIT_REPORT.json and any JSON artefact that is a top-
    level object. Arrays / scalars are skipped (the concept doesn't
    apply). Idempotent: re-writes the value if one already exists.
    """
    target = Path(path)
    if not target.is_file():
        return False
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    prev_label = data.get("confidence")
    prev_reason = data.get("confidence_reasoning")
    if prev_label == label and prev_reason == reasoning:
        return False
    data["confidence"] = label
    data["confidence_reasoning"] = reasoning
    try:
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


def stamp_all_reports(
    *,
    agent_team_dir: str | Path,
    signals: ConfidenceSignals,
    config: Any | None = None,
) -> dict[str, bool]:
    """Walk ``agent_team_dir`` and stamp every user-facing report.

    Returns a mapping of ``{path: modified_bool}`` for observability.
    A False ``v18.confidence_banners_enabled`` short-circuits — empty
    dict returned so the caller can log "banners disabled".
    """
    if config is not None and not confidence_banners_enabled(config):
        return {}

    root = Path(agent_team_dir)
    if not root.is_dir():
        return {}

    label, reasoning = derive_confidence(signals)
    touched: dict[str, bool] = {}

    # AUDIT_REPORT.json (top-level + per-milestone)
    for audit_json in list(root.glob("AUDIT_REPORT.json")) + list(
        root.glob("milestones/*/AUDIT_REPORT.json")
    ):
        touched[str(audit_json)] = stamp_json_report(
            audit_json, label=label, reasoning=reasoning,
        )

    # BUILD_LOG.txt
    for build_log in root.glob("BUILD_LOG.txt"):
        touched[str(build_log)] = stamp_build_log(
            build_log, label=label, reasoning=reasoning,
        )

    # GATE_*_REPORT.md (at root and per milestone)
    for gate_md in list(root.glob("GATE_*_REPORT.md")) + list(
        root.glob("milestones/*/GATE_*_REPORT.md")
    ):
        touched[str(gate_md)] = stamp_markdown_report(
            gate_md, label=label, reasoning=reasoning,
        )

    # *_RECOVERY_REPORT.md
    for rec_md in list(root.glob("*_RECOVERY_REPORT.md")) + list(
        root.glob("milestones/*/*_RECOVERY_REPORT.md")
    ):
        touched[str(rec_md)] = stamp_markdown_report(
            rec_md, label=label, reasoning=reasoning,
        )

    return touched

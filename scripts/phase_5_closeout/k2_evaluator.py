"""Phase 5.8a §K.2 decision-gate evaluator.

Reads every ``PHASE_5_8A_DIAGNOSTIC.json`` artifact under a smoke-batch
root, applies :func:`agent_team_v15.cross_package_diagnostic.k2_decision_gate_satisfied`,
and writes ``PHASE_5_8A_DIAGNOSTIC_SUMMARY.md`` with the outcome.

Per the Phase 5 closeout-smoke plan approver constraint #1: count
strict=ON diagnostics only by default; ``strict_mode=OFF`` and missing-
strict_mode diagnostics are EXCLUDED from §K.2 aggregation with an
explicit warning row in the summary. ``--include-strict-off`` overrides
the default and aggregates everything (operator must justify the
override in the smoke landing memo).

Decision branches per the Phase 5 plan §K.2 contract:

* **Outcome A** — predicate satisfied (≥ ``correlated-threshold``
  distinct DTOs share the same divergence_class across the kept
  diagnostics). Phase 5.8b ships full ``cross_package_contract.py``;
  must land BEFORE the v5 capstone smoke.
* **Outcome B** — predicate NOT satisfied. R-#42 closes via Wave A
  spec-quality investment (Phase 6+ scope). NOT blocking the capstone.
* **Indeterminate** — zero kept diagnostics after the strict-mode
  filter (e.g., all artifacts missing strict_mode label, or all
  strict=OFF under default policy). Per approver constraint, missing
  evidence labels do NOT count toward closure; this state must NOT
  silently fall through to Outcome B (which would close R-#42 from
  zero countable evidence). Operator must correct evidence labels
  before re-running.

Exit codes:

* ``0`` — Outcome A (decision triggered).
* ``1`` — Outcome B (decision did not trigger; R-#42 closes via
  Wave A spec-quality).
* ``2`` — Indeterminate / batch-root invalid / no diagnostics found.
  Operator action required: verify the batch root, confirm the
  diagnostic step ran during smokes, OR re-run with strict_mode
  recorded on every artifact.

The script is idempotent: re-running against the same batch produces
the same summary (modulo timestamp).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_team_v15.cross_package_diagnostic import (
    PHASE_5_8A_DIAGNOSTIC_FILENAME,
    k2_decision_gate_satisfied,
)


@dataclass
class _DiagnosticEntry:
    """One per-milestone diagnostic artifact discovered under the batch root."""

    smoke_run_dir: Path
    milestone_id: str
    strict_mode: str | None  # "ON" / "OFF" / None (missing)
    payload: dict[str, Any]


_STRICT_ON_TOKENS = frozenset({"ON", "TRUE", "1", "YES"})
_STRICT_OFF_TOKENS = frozenset({"OFF", "FALSE", "0", "NO"})


def _extract_strict_mode(payload: dict[str, Any]) -> str | None:
    """Look for strict_mode under several plausible keys.

    Phase 5.8a's writer at HEAD ``34bab7a`` does not record strict_mode.
    Operators executing closeout-smoke Stage 2 should add the field
    either via a wrapper around the smoke command or a small additive
    patch to ``cross_package_diagnostic.write_phase_5_8a_diagnostic``.
    This evaluator accepts the field at the top level OR under
    ``metrics``/``tooling`` so multiple plausible recording strategies
    work.
    """

    candidates = [
        payload.get("strict_mode"),
        payload.get("tsc_strict_check_enabled"),
        (payload.get("metrics") or {}).get("strict_mode"),
        (payload.get("tooling") or {}).get("strict_mode"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        token = str(candidate).strip().upper()
        if token in _STRICT_ON_TOKENS:
            return "ON"
        if token in _STRICT_OFF_TOKENS:
            return "OFF"
    return None


def _discover_diagnostics(batch_root: Path) -> list[_DiagnosticEntry]:
    """Walk *batch_root* for per-milestone diagnostic JSON artifacts.

    Expected on-disk layout (per Phase 5.8a §K.1 + correction #3):
    ``<batch_root>/<smoke_run_dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json``.

    Malformed JSON / non-dict payloads are silently skipped — the
    evaluator never crashes on a bad artifact (the batch's other
    smokes' diagnostics still count). Operator should investigate
    skipped paths via the summary's "diagnostics not parsed" footnote.
    """

    if not batch_root.is_dir():
        return []
    pattern = f"*/.agent-team/milestones/*/{PHASE_5_8A_DIAGNOSTIC_FILENAME}"
    entries: list[_DiagnosticEntry] = []
    for path in sorted(batch_root.glob(pattern)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        # path = <batch>/<run-dir>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json
        # parents[0] = <id>/, [1] = milestones/, [2] = .agent-team/, [3] = <run-dir>/
        smoke_run_dir = path.parents[3]
        milestone_id = str(payload.get("milestone_id", path.parent.name))
        strict_mode = _extract_strict_mode(payload)
        entries.append(
            _DiagnosticEntry(
                smoke_run_dir=smoke_run_dir,
                milestone_id=milestone_id,
                strict_mode=strict_mode,
                payload=payload,
            )
        )
    return entries


def _filter_for_k2(
    entries: list[_DiagnosticEntry],
    *,
    include_strict_off: bool,
) -> tuple[list[_DiagnosticEntry], list[str]]:
    """Apply the §K.2 default filter: strict=ON only; warn on missing.

    Returns a (kept, warnings) tuple. With ``include_strict_off=True``
    the filter is bypassed entirely (operator override).
    """

    if include_strict_off:
        return list(entries), [
            "Operator override: --include-strict-off ACTIVE; aggregating "
            "strict=ON, strict=OFF, and missing-strict-mode diagnostics "
            "as identical. Per approver constraint #1 this MUST be "
            "explicitly justified in the smoke landing memo."
        ]
    kept: list[_DiagnosticEntry] = []
    excluded_off = 0
    excluded_missing = 0
    for entry in entries:
        if entry.strict_mode == "ON":
            kept.append(entry)
        elif entry.strict_mode == "OFF":
            excluded_off += 1
        else:
            excluded_missing += 1
    warnings: list[str] = []
    if excluded_off:
        warnings.append(
            f"Excluded {excluded_off} strict_mode=OFF diagnostic(s) from "
            f"§K.2 aggregation (default policy: strict=ON only)."
        )
    if excluded_missing:
        warnings.append(
            f"Excluded {excluded_missing} diagnostic(s) without "
            f"strict_mode field. Per approver constraint #1 the field "
            f"is mandatory; smokes without it cannot count toward §K.2. "
            f"Either re-run with strict_mode recording or use "
            f"--include-strict-off to explicitly aggregate (NOT "
            f"recommended)."
        )
    return kept, warnings


def _entries_to_diag_dicts(
    entries: list[_DiagnosticEntry],
) -> list[dict[str, Any]]:
    """Reshape into the list ``k2_decision_gate_satisfied`` expects."""

    return [
        {
            "milestone_id": e.milestone_id,
            "divergences": list(e.payload.get("divergences", []) or []),
        }
        for e in entries
    ]


def _render_summary_md(
    *,
    batch_id: str,
    head_sha: str | None,
    status: str,  # "A", "B", or "indeterminate"
    threshold: int,
    entries_kept: list[_DiagnosticEntry],
    entries_all: list[_DiagnosticEntry],
    warnings: list[str],
    include_strict_off: bool,
) -> str:
    """Render the PHASE_5_8A_DIAGNOSTIC_SUMMARY.md content."""

    lines: list[str] = [
        "# PHASE_5_8A_DIAGNOSTIC_SUMMARY",
        "",
        f"- **Smoke batch ID:** {batch_id}",
        f"- **Source HEAD:** {head_sha or 'unrecorded — operator must record'}",
        f"- **Correlation threshold:** {threshold}",
        f"- **Strict-mode filter:** "
        + (
            "OPERATOR-OVERRIDE include-strict-off"
            if include_strict_off
            else "default (strict=ON only)"
        ),
        f"- **Diagnostics found:** {len(entries_all)} ({len(entries_kept)} kept)",
        "",
        "## Decision",
        "",
    ]
    if status == "A":
        lines.append(
            "**Outcome A — Phase 5.8b ships.** §K.2 predicate satisfied: "
            "at least 3 distinct DTOs share the same divergence_class "
            "across the kept diagnostics. Phase 5.8b implementation must "
            "land BEFORE the v5 capstone smoke."
        )
    elif status == "B":
        lines.append(
            "**Outcome B — Phase 5.8b does NOT ship; close R-#42 via Wave "
            "A spec-quality investment.** §K.2 predicate NOT satisfied "
            "across the kept diagnostics. The Wave A spec-quality "
            "investment is Phase 6+ scope and does NOT block the v5 "
            "capstone."
        )
    else:  # indeterminate
        if not entries_all:
            cause = (
                "no PHASE_5_8A_DIAGNOSTIC.json artifacts were found under "
                "the batch root. Verify the batch root path and that the "
                "Phase 5.8a diagnostic step actually ran during the smokes."
            )
        else:
            cause = (
                f"{len(entries_all)} diagnostic(s) were discovered but "
                f"NONE survived the default strict=ON filter (per "
                f"approver constraint #1). Missing evidence labels do "
                f"not count toward §K.2 closure; the decision cannot be "
                f"made until the evidence is corrected. Either re-run "
                f"the smokes with strict_mode recorded on every "
                f"artifact, or use ``--include-strict-off`` with explicit "
                f"justification (NOT recommended)."
            )
        lines.append(
            f"**Indeterminate — no decision.** §K.2 evaluation has zero "
            f"countable evidence: {cause}"
        )
    lines.extend(
        [
            "",
            "## Evidence — kept diagnostics (counted toward §K.2)",
            "",
        ]
    )
    if not entries_kept:
        lines.append(
            "No diagnostics were kept after the strict-mode filter. The "
            "§K.2 predicate is vacuously False (no divergences to "
            "correlate)."
        )
    else:
        lines.append(
            "| Smoke run-dir | Milestone | strict_mode | divergence count | unique classes |"
        )
        lines.append("|---|---|---|---|---|")
        for entry in entries_kept:
            divergences = entry.payload.get("divergences", []) or []
            unique_classes = sorted(
                {
                    str(d.get("divergence_class", "?"))
                    for d in divergences
                    if isinstance(d, dict)
                }
            )
            lines.append(
                f"| {entry.smoke_run_dir.name} | {entry.milestone_id} | "
                f"{entry.strict_mode or '?'} | {len(divergences)} | "
                f"{', '.join(unique_classes) or '—'} |"
            )
    lines.append("")
    excluded = [e for e in entries_all if e not in entries_kept]
    if excluded:
        lines.extend(
            [
                "## Evidence — excluded diagnostics (NOT counted)",
                "",
                "| Smoke run-dir | Milestone | strict_mode | reason |",
                "|---|---|---|---|",
            ]
        )
        for entry in excluded:
            if entry.strict_mode == "OFF":
                reason = "strict_mode=OFF (default §K.2 filter)"
            else:
                reason = "missing strict_mode field"
            lines.append(
                f"| {entry.smoke_run_dir.name} | {entry.milestone_id} | "
                f"{entry.strict_mode or '∅'} | {reason} |"
            )
        lines.append("")
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("## Next steps")
    lines.append("")
    if status == "A":
        lines.extend(
            [
                "1. Author the Phase 5.8b implementation (full "
                "``cross_package_contract.py``) per the existing Phase 5.8 "
                "brief in ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §K.",
                "2. Land 5.8b source + 1 live M1+M2 smoke validating the new contract.",
                "3. Then release Capstone (Smoke 3) per the closeout-smoke plan.",
            ]
        )
    elif status == "B":
        lines.extend(
            [
                "1. R-#42 closes via Wave A spec-quality investment — "
                "Phase 6+ scope; NOT blocking the v5 capstone.",
                "2. Document Outcome B in the v5 closeout landing memo "
                "with the evidence rows above.",
                "3. Release Capstone (Smoke 3) per the closeout-smoke plan.",
            ]
        )
    else:  # indeterminate
        lines.extend(
            [
                "1. Do NOT release Capstone — §K.2 evaluation produced "
                "no decision. The closeout-smoke plan requires an "
                "explicit Outcome A or Outcome B before capstone.",
                "2. Verify the batch root + that the Phase 5.8a "
                "diagnostic step actually ran during smokes.",
                "3. If diagnostics exist but lack ``strict_mode``: "
                "re-run with strict_mode recorded on every artifact, "
                "OR patch ``cross_package_diagnostic.write_phase_5_8a_diagnostic`` "
                "to thread the field from config (additive change).",
                "4. Re-run this evaluator with corrected evidence.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def evaluate(
    *,
    batch_root: Path,
    smoke_batch_id: str,
    head_sha: str | None,
    correlated_threshold: int,
    include_strict_off: bool,
) -> tuple[str, str, list[_DiagnosticEntry], list[_DiagnosticEntry]]:
    """Run the full evaluation and return (status, summary_md, kept, all).

    ``status`` is one of:

    * ``"A"`` — §K.2 predicate satisfied; Phase 5.8b ships.
    * ``"B"`` — §K.2 predicate not satisfied; close R-#42 via Wave A.
    * ``"indeterminate"`` — no countable evidence (zero kept after the
      strict-mode filter, OR no diagnostics found at all). Per
      approver constraint, missing evidence labels do NOT count toward
      closure; this state must NOT silently become Outcome B.

    Public function so tests can drive the evaluator without re-parsing
    argv.
    """

    entries = _discover_diagnostics(batch_root)
    kept, warnings = _filter_for_k2(entries, include_strict_off=include_strict_off)

    # Three-way status: indeterminate when no kept evidence (regardless
    # of why); A/B when the predicate runs against ≥1 kept diagnostic.
    if not kept:
        status = "indeterminate"
    else:
        diag_dicts = _entries_to_diag_dicts(kept)
        decision = k2_decision_gate_satisfied(
            diag_dicts, correlated_threshold=correlated_threshold,
        )
        status = "A" if decision else "B"

    summary = _render_summary_md(
        batch_id=smoke_batch_id,
        head_sha=head_sha,
        status=status,
        threshold=correlated_threshold,
        entries_kept=kept,
        entries_all=entries,
        warnings=warnings,
        include_strict_off=include_strict_off,
    )
    return status, summary, kept, entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5.8a §K.2 decision-gate evaluator.",
    )
    parser.add_argument(
        "--batch-root",
        type=Path,
        required=True,
        help="Directory containing per-smoke run-dirs (e.g. 'v18 test runs/').",
    )
    parser.add_argument(
        "--smoke-batch-id",
        default="unspecified",
        help="Operator-supplied label for this batch (e.g. 'phase-5-8a-2026-05-12').",
    )
    parser.add_argument(
        "--head-sha",
        default=None,
        help="Source HEAD the batch ran against (recorded in the summary).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("PHASE_5_8A_DIAGNOSTIC_SUMMARY.md"),
        help="Output path for the summary markdown.",
    )
    parser.add_argument(
        "--correlated-threshold",
        type=int,
        default=3,
        help="§K.2 predicate correlation threshold (default 3).",
    )
    parser.add_argument(
        "--include-strict-off",
        action="store_true",
        help=(
            "OVERRIDE: aggregate strict=ON + strict=OFF + missing as "
            "identical (NOT recommended; explicitly documented in summary)."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print summary to stdout instead of writing to --output.",
    )
    args = parser.parse_args(argv)

    status, summary, _kept, entries_all = evaluate(
        batch_root=args.batch_root,
        smoke_batch_id=args.smoke_batch_id,
        head_sha=args.head_sha,
        correlated_threshold=args.correlated_threshold,
        include_strict_off=args.include_strict_off,
    )

    if args.print_only:
        print(summary)
    else:
        args.output.write_text(summary, encoding="utf-8")
        print(f"[K.2-EVAL] Wrote summary to {args.output}", file=sys.stderr)

    if status == "indeterminate":
        if not entries_all:
            print(
                f"[K.2-EVAL] Indeterminate: no PHASE_5_8A_DIAGNOSTIC.json "
                f"artifacts found under {args.batch_root}. Verify the "
                f"batch root + that the diagnostic step ran during "
                f"smokes.",
                file=sys.stderr,
            )
        else:
            print(
                f"[K.2-EVAL] Indeterminate: {len(entries_all)} "
                f"diagnostic(s) discovered but ZERO survived the "
                f"default strict=ON filter. Missing evidence labels "
                f"do not count toward §K.2 closure; correct the "
                f"evidence and re-run.",
                file=sys.stderr,
            )
        return 2
    return 0 if status == "A" else 1


if __name__ == "__main__":
    sys.exit(main())

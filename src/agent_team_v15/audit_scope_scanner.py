"""Phase F — auditor scope completeness scanner.

Catches silent "pass" because a Day-1 requirement falls out of the
auditor's surface. Before a milestone audit runs, the scanner checks
that every requirement in ``REQUIREMENTS.md`` has at least one auditor
or scanner covering it. When a requirement has no coverage it emits
an ``AUDIT-SCOPE-GAP`` meta-finding so operators see the gap instead
of a silent green audit.

Requirements covered by built-in scanner surfaces
=================================================

  * i18n / RTL enforcement — covered by the forbidden-content scanner
    (N-10) when ``v18.content_scope_scanner_enabled`` is True.
  * UI_DESIGN_TOKENS.json presence — covered by a filesystem check.
  * stack_contract compliance — covered by the scaffold-verifier +
    stack contract validation that runs at Wave-A wire-up.
  * Any requirement that names a file / path explicitly — covered by
    the scorer's file-level evidence requirements.

Everything else falls through to the LLM auditor's qualitative read.
When a requirement's body mentions *none* of the recognised coverage
markers AND no active scanner matches the requirement's file hints,
the scanner emits an ``AUDIT-SCOPE-GAP`` meta-finding with:

  * the requirement ID and title
  * the list of coverage categories it was checked against
  * a suggested remediation (add a scanner, extend the auditor surface)

The module is purely additive and deterministic — no LLM calls — and
it only emits ``INFO``-severity findings so it never fails an audit on
its own. The intent is *visibility*, not gating.

Flag: ``v18.audit_scope_completeness_enabled`` (default True).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class CoverageCheck:
    """A deterministic coverage probe for a requirement category."""

    name: str
    keywords: tuple[str, ...]
    scanner_present: bool = False
    detail: str = ""


@dataclass
class ScopeGap:
    """One uncovered requirement."""

    requirement_id: str
    title: str
    checked_against: list[str] = field(default_factory=list)
    reason: str = ""


def audit_scope_completeness_enabled(config: Any) -> bool:
    v18 = getattr(config, "v18", None)
    return bool(getattr(v18, "audit_scope_completeness_enabled", True))


_REQUIREMENT_ID_PATTERN = re.compile(r"^-\s*\[[ xX]\]\s*(REQ-[A-Z0-9-]+|AC-[A-Z0-9-]+):\s*(.+?)(?:\s*\(|$)")


def _parse_requirements_md(path: Path) -> list[tuple[str, str]]:
    """Extract ``(id, title)`` pairs from a REQUIREMENTS.md file.

    Matches both ``REQ-...`` and ``AC-...`` IDs so upstream callers
    can feed either a per-milestone REQUIREMENTS.md (REQ-ids) or a
    top-level AC list. Titles are trimmed at any trailing
    ``(review_cycles: ...)`` marker so the returned string is the
    human-readable requirement name.
    """
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _REQUIREMENT_ID_PATTERN.match(line.strip())
        if not match:
            continue
        req_id = match.group(1).strip()
        title = match.group(2).strip()
        out.append((req_id, title))
    return out


def _coverage_checks(config: Any, cwd: Path) -> list[CoverageCheck]:
    """Build the list of coverage probes based on current config + cwd."""
    v18 = getattr(config, "v18", None)
    content_scope_on = bool(
        getattr(v18, "content_scope_scanner_enabled", False)
    )
    scaffold_verifier_report = cwd / ".agent-team" / "scaffold_verifier_report.json"
    design_tokens_path = cwd / "UI_DESIGN_TOKENS.json"
    design_tokens_nested = cwd / ".agent-team" / "UI_DESIGN_TOKENS.json"

    return [
        CoverageCheck(
            name="i18n_rtl",
            keywords=("i18n", "rtl", "arabic", "translation", "locale"),
            scanner_present=content_scope_on,
            detail=(
                "forbidden_content_scanner (N-10) active"
                if content_scope_on
                else "N-10 scanner disabled — enable "
                "v18.content_scope_scanner_enabled to cover"
            ),
        ),
        CoverageCheck(
            name="design_tokens",
            keywords=(
                "design tokens",
                "design token",
                "ui_design_tokens",
                "ui design tokens",
            ),
            scanner_present=(
                design_tokens_path.is_file() or design_tokens_nested.is_file()
            ),
            detail=(
                "UI_DESIGN_TOKENS.json present"
                if (
                    design_tokens_path.is_file()
                    or design_tokens_nested.is_file()
                )
                else "UI_DESIGN_TOKENS.json missing — create at repo root or "
                ".agent-team/"
            ),
        ),
        CoverageCheck(
            name="stack_contract",
            keywords=(
                "stack contract",
                "stack_contract",
                "scaffold ownership",
                "scaffold_ownership",
                "scaffold contract",
            ),
            scanner_present=scaffold_verifier_report.is_file(),
            detail=(
                "scaffold_verifier_report.json present"
                if scaffold_verifier_report.is_file()
                else "scaffold_verifier_report.json missing — scaffold "
                "verifier has not run yet"
            ),
        ),
    ]


def _requirement_has_coverage(
    title: str,
    req_id: str,
    coverage_checks: list[CoverageCheck],
) -> tuple[bool, list[str], list[str]]:
    """Return ``(is_covered, matched_categories, missing_categories)``.

    A requirement is "covered" if
      * it mentions a keyword for a category AND that category's scanner
        is present; OR
      * it mentions an explicit file path (``apps/...``, ``packages/...``,
        ``src/...``, ``docs/...``) — the LLM scorer will evaluate file
        presence / content directly.

    If a requirement references a keyword whose scanner is NOT present,
    the check is treated as "missing coverage" for that category.
    """
    text = f"{req_id} {title}".lower()
    matched: list[str] = []
    missing: list[str] = []
    for check in coverage_checks:
        hit = any(kw in text for kw in check.keywords)
        if not hit:
            continue
        if check.scanner_present:
            matched.append(check.name)
        else:
            missing.append(check.name)
    # File-path implicit coverage.
    if re.search(r"(?:apps|packages|src|docs)/[A-Za-z0-9_\-./]+", title):
        matched.append("file_path_evidence")
    return (bool(matched) and not missing, matched, missing)


def scan_audit_scope(
    *,
    cwd: str | Path,
    requirements_path: str | Path,
    config: Any,
) -> list[ScopeGap]:
    """Walk the requirements list and return every uncovered requirement.

    Args:
        cwd: project root (the one that contains ``.agent-team/``).
        requirements_path: absolute path to the REQUIREMENTS.md to scan.
        config: active :class:`AgentTeamConfig`.

    Returns:
        A list of :class:`ScopeGap` — empty when every requirement is
        covered by at least one active scanner or file-path evidence.
        Flag off (``v18.audit_scope_completeness_enabled`` False)
        returns an empty list regardless of state.
    """
    if not audit_scope_completeness_enabled(config):
        return []

    req_path = Path(requirements_path)
    cwd_path = Path(cwd)
    requirements = _parse_requirements_md(req_path)
    if not requirements:
        return []

    coverage = _coverage_checks(config, cwd_path)
    gaps: list[ScopeGap] = []
    category_names = [c.name for c in coverage] + ["file_path_evidence"]

    for req_id, title in requirements:
        covered, matched, missing = _requirement_has_coverage(
            title, req_id, coverage,
        )
        if covered:
            continue
        if missing:
            reason = (
                f"references {', '.join(missing)} but the matching scanner "
                "is not active — requirement cannot be verified deterministically."
            )
        else:
            # No keyword / file-path matched any category at all.
            reason = (
                "no scanner / auditor surface matched this requirement's "
                "keywords or file paths — only LLM qualitative scoring applies."
            )
        gaps.append(
            ScopeGap(
                requirement_id=req_id,
                title=title,
                checked_against=category_names,
                reason=reason,
            )
        )

    if gaps:
        logger.info(
            "audit_scope_scanner: %d requirement(s) have no deterministic "
            "auditor coverage under %s",
            len(gaps),
            req_path,
        )
    return gaps


def build_scope_gap_findings(gaps: Iterable[ScopeGap]) -> list[dict[str, Any]]:
    """Serialise ``ScopeGap``s into audit-finding dicts.

    Returns dicts compatible with ``AuditFinding(**payload)`` so the
    caller can pass each one through the normal finding merge path.
    Severity is INFO so the meta-findings never fail an audit alone —
    they only surface the gap.
    """
    out: list[dict[str, Any]] = []
    for gap in gaps:
        finding_id = f"AUDIT-SCOPE-GAP-{gap.requirement_id}"
        out.append(
            {
                "finding_id": finding_id,
                "auditor": "audit-scope-scanner",
                "requirement_id": gap.requirement_id,
                "verdict": "UNVERIFIED",
                "severity": "INFO",
                "summary": (
                    f"AUDIT-SCOPE-GAP: '{gap.title}' has no auditor / "
                    "scanner coverage."
                ),
                "evidence": [
                    f"Checked against: {', '.join(gap.checked_against)}",
                    gap.reason,
                ],
                "remediation": (
                    "Add a deterministic scanner (or extend an existing "
                    "auditor prompt) to cover this requirement. Until then "
                    "the requirement relies on LLM qualitative judgment "
                    "only, which can mask silent regressions."
                ),
                "source": "deterministic",
            }
        )
    return out

"""Milestone SPEC reconciler — N-12 (Phase B).

Merges per-run inputs (REQUIREMENTS.md, PRD, stack contract, ownership
contract) into a single resolved manifest that drives scaffold emission and
wave-prompt claims. When sources disagree on a concrete value, REQUIREMENTS
wins over PRD and the conflict is recorded in ``RECONCILIATION_CONFLICTS.md``
so the reviewer can arbitrate.

See ``docs/plans/2026-04-16-phase-b-architecture-report.md`` §5 for the full
design rationale. This module is flagged off by default
(``v18.spec_reconciliation_enabled=False``) — the orchestrator falls back to
:data:`agent_team_v15.scaffold_runner.DEFAULT_SCAFFOLD_CONFIG` in that case.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .scaffold_runner import (
    DEFAULT_SCAFFOLD_CONFIG,
    OwnershipContract,
    ScaffoldConfig,
)


@dataclass(frozen=True)
class SpecConflict:
    """A disagreement between two reconciliation inputs on one canonical field."""

    section: str  # e.g. "port", "prisma_path"
    source_a: str  # e.g. "REQUIREMENTS.md"
    source_a_value: str
    source_b: str
    source_b_value: str
    winner: str  # which source the reconciler picked
    winning_value: str

    def as_row(self) -> str:
        return (
            f"- **{self.section}**: {self.source_a}={self.source_a_value!r} vs "
            f"{self.source_b}={self.source_b_value!r} -> chose {self.winner} "
            f"({self.winning_value!r}); arbitration required"
        )


@dataclass
class SpecReconciliationResult:
    """Output of :func:`reconcile_milestone_spec`."""

    merged_spec: dict[str, Any]
    conflicts: list[SpecConflict]
    resolved_scaffold_config: ScaffoldConfig
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    def recovery_type(self) -> Optional[str]:
        return "reconciliation_arbitration_required" if self.has_conflicts else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reconcile_milestone_spec(
    requirements_path: Path,
    prd_path: Optional[Path],
    stack_contract: Optional[dict[str, Any]],
    ownership_contract: OwnershipContract,
    *,
    milestone_id: str = "milestone-unknown",
    output_dir: Optional[Path] = None,
) -> SpecReconciliationResult:
    """Merge REQUIREMENTS + PRD + stack-contract + ownership into a resolved SPEC.

    Precedence (highest to lowest):
      1. Ownership contract (file ownership assignments; structural).
      2. Stack contract (framework invariants such as apps/api path).
      3. M1 REQUIREMENTS.md (per-milestone canonical).
      4. PRD (project-wide baseline).

    Writes ``SPEC.md`` + ``resolved_manifest.json`` to *output_dir* when
    provided. Writes ``RECONCILIATION_CONFLICTS.md`` to the same directory
    only when at least one conflict exists.
    """

    requirements_text = _safe_read(requirements_path)
    prd_text = _safe_read(prd_path) if prd_path is not None else ""

    req_values = _extract_scaffold_values_from_requirements(requirements_text)
    prd_values = _extract_scaffold_values_from_prd(prd_text)
    stack_values = _extract_scaffold_values_from_stack_contract(stack_contract or {})

    conflicts: list[SpecConflict] = []
    sources: dict[str, str] = {}
    resolved: dict[str, Any] = {}

    defaults = DEFAULT_SCAFFOLD_CONFIG
    fields = ("port", "prisma_path", "modules_path", "api_prefix", "db_name", "db_user")

    for field_name in fields:
        req_val = req_values.get(field_name)
        prd_val = prd_values.get(field_name)
        stack_val = stack_values.get(field_name)

        # Stack contract wins when it speaks; it encodes framework invariants.
        if stack_val is not None and req_val is not None and stack_val != req_val:
            conflicts.append(
                SpecConflict(
                    section=field_name,
                    source_a="stack_contract",
                    source_a_value=str(stack_val),
                    source_b="REQUIREMENTS.md",
                    source_b_value=str(req_val),
                    winner="stack_contract",
                    winning_value=str(stack_val),
                )
            )

        # REQUIREMENTS wins over PRD on direct disagreement.
        if req_val is not None and prd_val is not None and req_val != prd_val:
            conflicts.append(
                SpecConflict(
                    section=field_name,
                    source_a="REQUIREMENTS.md",
                    source_a_value=str(req_val),
                    source_b="PRD",
                    source_b_value=str(prd_val),
                    winner="REQUIREMENTS.md",
                    winning_value=str(req_val),
                )
            )

        if stack_val is not None:
            resolved[field_name] = stack_val
            sources[field_name] = "stack_contract"
        elif req_val is not None:
            resolved[field_name] = req_val
            sources[field_name] = "REQUIREMENTS.md"
        elif prd_val is not None:
            resolved[field_name] = prd_val
            sources[field_name] = "PRD"
        else:
            resolved[field_name] = getattr(defaults, field_name)
            sources[field_name] = "default"

    scaffold_cfg = ScaffoldConfig(
        port=int(resolved["port"]),
        prisma_path=str(resolved["prisma_path"]),
        modules_path=str(resolved["modules_path"]),
        api_prefix=str(resolved["api_prefix"]),
        db_name=str(resolved["db_name"]),
        db_user=str(resolved["db_user"]),
    )

    merged_spec: dict[str, Any] = {
        "milestone_id": milestone_id,
        "scaffold_config": {
            "port": scaffold_cfg.port,
            "prisma_path": scaffold_cfg.prisma_path,
            "modules_path": scaffold_cfg.modules_path,
            "api_prefix": scaffold_cfg.api_prefix,
            "db_name": scaffold_cfg.db_name,
            "db_user": scaffold_cfg.db_user,
        },
        "sources": dict(sources),
        "ownership_counts": {
            "scaffold": len(ownership_contract.files_for_owner("scaffold")),
            "wave-b": len(ownership_contract.files_for_owner("wave-b")),
            "wave-d": len(ownership_contract.files_for_owner("wave-d")),
            "wave-c-generator": len(ownership_contract.files_for_owner("wave-c-generator")),
        },
        "conflicts": [
            {
                "section": c.section,
                "source_a": c.source_a,
                "source_a_value": c.source_a_value,
                "source_b": c.source_b,
                "source_b_value": c.source_b_value,
                "winner": c.winner,
                "winning_value": c.winning_value,
            }
            for c in conflicts
        ],
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_spec_md(output_dir / "SPEC.md", milestone_id, scaffold_cfg, sources, conflicts)
        (output_dir / "resolved_manifest.json").write_text(
            json.dumps(merged_spec, indent=2) + "\n", encoding="utf-8"
        )
        if conflicts:
            _write_conflicts_md(output_dir / "RECONCILIATION_CONFLICTS.md", milestone_id, conflicts)

    return SpecReconciliationResult(
        merged_spec=merged_spec,
        conflicts=conflicts,
        resolved_scaffold_config=scaffold_cfg,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Input extraction helpers
# ---------------------------------------------------------------------------


_PORT_LINE_RE = re.compile(r"^\s*PORT\s*=\s*(\d+)\s*$", re.MULTILINE)
_PORT_INLINE_RE = re.compile(r"\bPORT\s*=\s*(\d+)\b")
_PORT_YAML_RE = re.compile(r"PORT\s*:\s*['\"]?(\d+)['\"]?", re.IGNORECASE)
_PRISMA_PATH_RE = re.compile(r"apps/api/src/(database|prisma)/prisma\.(service|module)\.ts")
_MODULES_PATH_RE = re.compile(r"apps/api/src/(modules/)?[a-z0-9_-]+/[a-z0-9_-]+\.module\.ts")
_API_PREFIX_RE = re.compile(r"setGlobalPrefix\(['\"]([^'\"]+)['\"]")
_DB_URL_RE = re.compile(r"postgres(?:ql)?://([A-Za-z0-9_-]+):[^@]+@[A-Za-z0-9.-]+:\d+/([A-Za-z0-9_-]+)")


def _safe_read(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def _extract_scaffold_values_from_requirements(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not text:
        return out

    port_match = (
        _PORT_LINE_RE.search(text)
        or _PORT_INLINE_RE.search(text)
        or _PORT_YAML_RE.search(text)
    )
    if port_match is not None:
        try:
            out["port"] = int(port_match.group(1))
        except ValueError:
            pass

    prisma_match = _PRISMA_PATH_RE.search(text)
    if prisma_match is not None:
        out["prisma_path"] = f"src/{prisma_match.group(1)}"

    if "apps/api/src/modules/" in text:
        out["modules_path"] = "src/modules"
    elif _MODULES_PATH_RE.search(text):
        # Fall through — exact shape ambiguous; don't infer.
        pass

    prefix_match = _API_PREFIX_RE.search(text)
    if prefix_match is not None:
        out["api_prefix"] = prefix_match.group(1).strip("/") or "api"

    db_match = _DB_URL_RE.search(text)
    if db_match is not None:
        out["db_user"] = db_match.group(1)
        out["db_name"] = db_match.group(2)

    return out


def _extract_scaffold_values_from_prd(text: str) -> dict[str, Any]:
    # PRD is free-form; apply the same regex set but treat absence as silent.
    return _extract_scaffold_values_from_requirements(text)


def _extract_scaffold_values_from_stack_contract(stack: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(stack, dict):
        return out
    if "port" in stack and isinstance(stack["port"], (int, str)):
        try:
            out["port"] = int(stack["port"])
        except (ValueError, TypeError):
            pass
    if "api_prefix" in stack and isinstance(stack["api_prefix"], str):
        out["api_prefix"] = stack["api_prefix"]
    return out


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_spec_md(
    path: Path,
    milestone_id: str,
    cfg: ScaffoldConfig,
    sources: dict[str, str],
    conflicts: list[SpecConflict],
) -> None:
    lines = [
        f"# Resolved Milestone SPEC: {milestone_id}",
        "",
        "> Generated by `milestone_spec_reconciler.reconcile_milestone_spec`.",
        "> Precedence: stack_contract > REQUIREMENTS.md > PRD > default.",
        "",
        "## Scaffold Config",
        "",
        "| Field | Value | Source |",
        "|---|---|---|",
    ]
    for field_name in ("port", "prisma_path", "modules_path", "api_prefix", "db_name", "db_user"):
        lines.append(
            f"| `{field_name}` | `{getattr(cfg, field_name)}` | "
            f"{sources.get(field_name, 'default')} |"
        )
    lines.extend(["", "## Conflicts", ""])
    if conflicts:
        lines.append(f"{len(conflicts)} conflict(s) recorded. "
                     "See `RECONCILIATION_CONFLICTS.md` for the details and arbitration request.")
    else:
        lines.append("None.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_conflicts_md(path: Path, milestone_id: str, conflicts: list[SpecConflict]) -> None:
    lines = [
        f"# Reconciliation Conflicts: {milestone_id}",
        "",
        "> Emitted because two or more reconciliation inputs disagreed on a canonical value.",
        "> The reconciler picked a winner per precedence rules; a reviewer must confirm",
        "> (or override by editing REQUIREMENTS.md / PRD / stack_contract.json).",
        "",
        "## Conflicts",
        "",
    ]
    lines.extend(c.as_row() for c in conflicts)
    lines.extend(
        [
            "",
            "## Recovery",
            "",
            "Pipeline halts with `recovery_type: reconciliation_arbitration_required`.",
            "Reviewer choices:",
            "1. Accept each chosen winner above; delete this file to unblock the pipeline.",
            "2. Amend REQUIREMENTS.md / PRD / stack_contract.json to eliminate the conflict, then re-run.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
